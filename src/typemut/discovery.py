"""Find type annotation nodes in Python source using parso."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

import parso
from parso.python.tree import (
    BaseNode,
    Leaf,
    Module,
)

from typemut.nodes import NodeSource


class AnnotationContext(Enum):
    VARIABLE = "variable"
    PARAMETER = "parameter"
    RETURN = "return"
    TYPEVAR = "typevar"


@dataclass
class AnnotationNode:
    file: Path
    node: BaseNode | Leaf
    context: AnnotationContext
    line: int
    col: int
    code: str


# Lines with one of these comments are not mutated.
DEFAULT_SKIP_COMMENTS: tuple[str, ...] = ("type: ignore", "pragma: no mutate")

# Annotation nodes found by their parent node's type.
_ANNOTATION_CONTEXTS: Final = {
    "annassign": AnnotationContext.VARIABLE,
    "tfpdef": AnnotationContext.PARAMETER,
    "funcdef": AnnotationContext.RETURN,
}


@dataclass
class _Scan:
    """State of one :meth:`AnnotationFinder.find` call."""

    file: Path
    lines: Sequence[str]
    bare_typevar: bool
    qualified_typevar: bool
    annotations: list[AnnotationNode] = field(default_factory=list)


class SourceFiles:
    """The Python files under *module_path*, minus those matching *excluded_modules* globs."""

    def __init__(self, module_path: Path, excluded_modules: Iterable[str] = ()) -> None:
        self.module_path = module_path
        self._excluded = tuple(excluded_modules)

    def find(self) -> list[Path]:
        """Find all Python files in the module path, respecting exclusions."""
        return [
            py_file
            for py_file in sorted(self.module_path.rglob("*.py"))
            if not any(fnmatch.fnmatch(str(py_file), pattern) for pattern in self._excluded)
        ]


class AnnotationFinder(NodeSource):
    """Finds the type annotation nodes of a module.

    Annotations on lines containing one of *skip_comments* and bare ``Any``
    annotations are skipped.
    """

    def __init__(self, skip_comments: Iterable[str] = DEFAULT_SKIP_COMMENTS) -> None:
        self._skip_comments = tuple(skip_comments)

    def find(self, file: Path, source: str | None = None) -> list[AnnotationNode]:
        """Discover all type annotation nodes in *source*, read from *file* by default."""
        if source is None:
            source = file.read_text()
        tree = parso.parse(source)
        bare_typevar, qualified_typevar = self._has_typing_typevar_import(tree)
        scan = _Scan(file, source.splitlines(), bare_typevar, qualified_typevar)
        self._visit(tree, scan)
        return scan.annotations

    def _visit(self, node: BaseNode | Leaf, scan: _Scan) -> None:
        if not isinstance(node, BaseNode):
            return
        # TypeVar declaration: T = TypeVar("T", ...)
        if node.type == "expr_stmt" and (scan.bare_typevar or scan.qualified_typevar):
            call_node = self._is_typevar_call(node, scan.bare_typevar, scan.qualified_typevar)
            if call_node is not None:
                self._add(scan, call_node, AnnotationContext.TYPEVAR)
                # Don't return; still recurse for nested annotations
        context = _ANNOTATION_CONTEXTS.get(node.type)
        if context is not None:
            ann = self._annotation(node)
            if ann is not None and not self._is_any(ann):
                self._add(scan, ann, context)
        for child in node.children:
            self._visit(child, scan)

    def _annotation(self, node: BaseNode) -> BaseNode | Leaf | None:
        """The annotation of an annassign (``x: int``), tfpdef (``x: int`` param) or funcdef."""
        if node.type == "annassign":
            return self._get_annotation_from_annassign(node)
        if node.type == "tfpdef":
            return self._get_annotation_from_tfpdef(node)
        return self._get_return_annotation(node)

    def _add(self, scan: _Scan, node: BaseNode | Leaf, context: AnnotationContext) -> None:
        line = node.start_pos[0]
        if self._should_skip_line(self._line_text(scan.lines, line)):
            return
        scan.annotations.append(
            AnnotationNode(
                file=scan.file,
                node=node,
                context=context,
                line=line,
                col=node.start_pos[1],
                code=self._node_code(node),
            )
        )

    def _has_typing_typevar_import(self, tree: Module) -> tuple[bool, bool]:
        """Check if TypeVar is imported from typing.

        Returns (bare_import, qualified_import) where:
        - bare_import: `from typing import TypeVar` (use as TypeVar(...))
        - qualified_import: `import typing` (use as typing.TypeVar(...))
        """
        bare = False
        qualified = False
        for child in tree.children:
            if isinstance(child, BaseNode):
                if child.type == "import_from":
                    # from typing import TypeVar  /  from typing import ..., TypeVar, ...
                    # Check the module is 'typing'
                    children_values = [
                        c.value if isinstance(c, Leaf) else "" for c in child.children
                    ]
                    if "typing" in children_values:
                        # Check imported names
                        for c in child.children:
                            if isinstance(c, Leaf) and c.value == "TypeVar":
                                bare = True
                            elif isinstance(c, BaseNode):
                                # import_as_names node
                                for sub in c.children:
                                    if isinstance(sub, Leaf) and sub.value == "TypeVar":
                                        bare = True
                elif child.type == "simple_stmt":
                    for sub in child.children:
                        if isinstance(sub, BaseNode) and sub.type == "import_name":
                            sub_code = sub.get_code()
                            if "import" in sub_code and "typing" in sub_code:
                                qualified = True
                        elif isinstance(sub, BaseNode) and sub.type == "import_from":
                            children_values = [
                                c.value if isinstance(c, Leaf) else "" for c in sub.children
                            ]
                            if "typing" in children_values:
                                for c in sub.children:
                                    if isinstance(c, Leaf) and c.value == "TypeVar":
                                        bare = True
                                    elif isinstance(c, BaseNode):
                                        for s in c.children:
                                            if isinstance(s, Leaf) and s.value == "TypeVar":
                                                bare = True
            elif isinstance(child, Leaf):
                pass  # skip plain leaves at module level
        return bare, qualified

    def _is_typevar_call(self, node: BaseNode, bare: bool, qualified: bool) -> BaseNode | None:
        """Check if an expr_stmt contains a TypeVar(...) call and return the call node.

        Handles both `T = TypeVar("T")` and `T = typing.TypeVar("T")`.
        """
        # expr_stmt: name '=' power/trailer/atom
        children = node.children
        if len(children) < 3:
            return None
        # Check for '=' operator
        has_assign = False
        for c in children:
            if isinstance(c, Leaf) and c.value == "=":
                has_assign = True
                break
        if not has_assign:
            return None

        # The RHS is everything after '='
        rhs = children[-1] if len(children) >= 3 else None
        if rhs is None:
            return None

        # Check for bare TypeVar(...) call — rhs is a power node: TypeVar trailer(...)
        # or an atom + trailer
        call_node = self._extract_typevar_power(rhs, bare, qualified)
        return call_node

    def _extract_typevar_power(
        self, node: BaseNode | Leaf, bare: bool, qualified: bool
    ) -> BaseNode | None:
        """Extract TypeVar(...) call from RHS of assignment."""
        if isinstance(node, BaseNode) and node.type in ("power", "atom_expr"):
            children = node.children
            # bare: TypeVar(...)  →  power: name('TypeVar') trailer('(' ... ')')
            if (
                bare
                and len(children) >= 2
                and isinstance(children[0], Leaf)
                and children[0].value == "TypeVar"
                and isinstance(children[1], BaseNode)
                and children[1].type == "trailer"
            ):
                return node
            # qualified: typing.TypeVar(...)  →  power: name('typing') trailer('.TypeVar') trailer('(' ... ')')
            if (
                qualified
                and len(children) >= 3
                and isinstance(children[0], Leaf)
                and children[0].value == "typing"
                and isinstance(children[1], BaseNode)
                and children[1].type == "trailer"
                and self._node_code(children[1]) == ".TypeVar"
                and isinstance(children[2], BaseNode)
                and children[2].type == "trailer"
            ):
                return node
        # It might also just be a simple call: TypeVar("T") parsed differently
        # Handle atom case: just name + trailer at expr_stmt level
        return None

    def _get_annotation_from_annassign(self, node: BaseNode) -> BaseNode | Leaf | None:
        """Extract annotation node from an annassign (e.g. `x: int = 5`).

        annassign structure: ':', annotation [, '=', value]
        The annotation is the child after the ':' operator.
        """
        children = node.children
        # children[0] is ':', children[1] is the annotation
        if len(children) >= 2:
            return children[1]
        return None

    def _get_annotation_from_tfpdef(self, node: BaseNode) -> BaseNode | Leaf | None:
        """Extract annotation node from a tfpdef (e.g. `x: int` in function params).

        tfpdef structure: name, ':', annotation
        """
        children = node.children
        if len(children) >= 3:
            return children[2]
        return None

    def _get_return_annotation(self, funcdef: BaseNode) -> BaseNode | Leaf | None:
        """Extract return annotation from funcdef.

        Look for '->' operator and take the next sibling.
        """
        children = funcdef.children
        for i, child in enumerate(children):
            if hasattr(child, "value") and child.value == "->" and i + 1 < len(children):
                return children[i + 1]
        return None

    def _line_text(self, file_lines: Sequence[str], line: int) -> str:
        """Get the text of a specific line (1-indexed)."""
        if 1 <= line <= len(file_lines):
            return file_lines[line - 1]
        return ""

    def _should_skip_line(self, line_text: str) -> bool:
        """Check if a line contains any skip comment."""
        return any(comment in line_text for comment in self._skip_comments)

    def _is_any(self, node: BaseNode | Leaf) -> bool:
        """Check if an annotation node is just `Any`."""
        return isinstance(node, Leaf) and node.value == "Any"
