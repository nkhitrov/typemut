"""Find type annotation nodes in Python source using parso."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import parso
from parso.python.tree import (
    BaseNode,
    Leaf,
    Module,
)


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


def _get_annotation_from_annassign(node: BaseNode) -> BaseNode | Leaf | None:
    """Extract annotation node from an annassign (e.g. `x: int = 5`).

    annassign structure: ':', annotation [, '=', value]
    The annotation is the child after the ':' operator.
    """
    children = node.children
    # children[0] is ':', children[1] is the annotation
    if len(children) >= 2:
        return children[1]
    return None


def _get_annotation_from_tfpdef(node: BaseNode) -> BaseNode | Leaf | None:
    """Extract annotation node from a tfpdef (e.g. `x: int` in function params).

    tfpdef structure: name, ':', annotation
    """
    children = node.children
    if len(children) >= 3:
        return children[2]
    return None


def _get_return_annotation(funcdef: BaseNode) -> BaseNode | Leaf | None:
    """Extract return annotation from funcdef.

    Look for '->' operator and take the next sibling.
    """
    children = funcdef.children
    for i, child in enumerate(children):
        if hasattr(child, "value") and child.value == "->" and i + 1 < len(children):
            return children[i + 1]
    return None


def _line_text(file_lines: list[str], line: int) -> str:
    """Get the text of a specific line (1-indexed)."""
    if 1 <= line <= len(file_lines):
        return file_lines[line - 1]
    return ""


def _should_skip_line(line_text: str, skip_comments: list[str]) -> bool:
    """Check if a line contains any skip comment."""
    return any(comment in line_text for comment in skip_comments)


def _is_any(node: BaseNode | Leaf) -> bool:
    """Check if an annotation node is just `Any`."""
    return isinstance(node, Leaf) and node.value == "Any"


def _has_typing_typevar_import(tree: Module) -> tuple[bool, bool]:
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
                children_values = [c.value if isinstance(c, Leaf) else "" for c in child.children]
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


def _is_typevar_call(node: BaseNode, bare: bool, qualified: bool) -> BaseNode | None:
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
    call_node = _extract_typevar_power(rhs, bare, qualified)
    return call_node


def _extract_typevar_power(node: BaseNode | Leaf, bare: bool, qualified: bool) -> BaseNode | None:
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
            and _node_code(children[1]) == ".TypeVar"
            and isinstance(children[2], BaseNode)
            and children[2].type == "trailer"
        ):
            return node
    # It might also just be a simple call: TypeVar("T") parsed differently
    # Handle atom case: just name + trailer at expr_stmt level
    return None


def discover_annotations(
    file: Path,
    source: str | None = None,
    skip_comments: list[str] | None = None,
) -> list[AnnotationNode]:
    """Discover all type annotation nodes in a Python source file."""
    if source is None:
        source = file.read_text()
    if skip_comments is None:
        skip_comments = ["type: ignore", "pragma: no mutate"]

    file_lines = source.splitlines()
    tree = parso.parse(source)
    annotations: list[AnnotationNode] = []

    # Check for TypeVar imports
    bare_typevar, qualified_typevar = _has_typing_typevar_import(tree)

    def visit(node: BaseNode | Leaf) -> None:
        if isinstance(node, BaseNode):
            # TypeVar declaration: T = TypeVar("T", ...)
            if node.type == "expr_stmt" and (bare_typevar or qualified_typevar):
                call_node = _is_typevar_call(node, bare_typevar, qualified_typevar)
                if call_node is not None:
                    line = call_node.start_pos[0]
                    if not _should_skip_line(_line_text(file_lines, line), skip_comments):
                        annotations.append(
                            AnnotationNode(
                                file=file,
                                node=call_node,
                                context=AnnotationContext.TYPEVAR,
                                line=line,
                                col=call_node.start_pos[1],
                                code=_node_code(call_node),
                            )
                        )
                    # Don't return; still recurse for nested annotations

            # Variable annotation: x: int
            if node.type == "annassign":
                ann = _get_annotation_from_annassign(node)
                if ann is not None and not _is_any(ann):
                    line = ann.start_pos[0]
                    if not _should_skip_line(_line_text(file_lines, line), skip_comments):
                        annotations.append(
                            AnnotationNode(
                                file=file,
                                node=ann,
                                context=AnnotationContext.VARIABLE,
                                line=line,
                                col=ann.start_pos[1],
                                code=ann.value if isinstance(ann, Leaf) else _node_code(ann),
                            )
                        )

            # Parameter annotation: def f(x: int)
            elif node.type == "tfpdef":
                ann = _get_annotation_from_tfpdef(node)
                if ann is not None and not _is_any(ann):
                    line = ann.start_pos[0]
                    if not _should_skip_line(_line_text(file_lines, line), skip_comments):
                        annotations.append(
                            AnnotationNode(
                                file=file,
                                node=ann,
                                context=AnnotationContext.PARAMETER,
                                line=line,
                                col=ann.start_pos[1],
                                code=ann.value if isinstance(ann, Leaf) else _node_code(ann),
                            )
                        )

            # Return annotation: def f() -> int
            elif node.type == "funcdef":
                ann = _get_return_annotation(node)
                if ann is not None and not _is_any(ann):
                    line = ann.start_pos[0]
                    if not _should_skip_line(_line_text(file_lines, line), skip_comments):
                        annotations.append(
                            AnnotationNode(
                                file=file,
                                node=ann,
                                context=AnnotationContext.RETURN,
                                line=line,
                                col=ann.start_pos[1],
                                code=ann.value if isinstance(ann, Leaf) else _node_code(ann),
                            )
                        )

            # Recurse into children
            for child in node.children:
                visit(child)

    visit(tree)
    return annotations


def _node_code(node: BaseNode | Leaf) -> str:
    """Get the exact source code text of a node, preserving whitespace."""
    code = node.get_code()
    # get_code() includes the prefix (leading whitespace) of the first leaf.
    # Strip it to get just the annotation text.
    first = node
    while hasattr(first, "children") and first.children:
        first = first.children[0]
    if hasattr(first, "prefix"):
        prefix = first.prefix
        if code.startswith(prefix):
            code = code[len(prefix) :]
    return code


def discover_files(
    module_path: Path,
    excluded_modules: list[str] | None = None,
) -> list[Path]:
    """Find all Python files in the given module path, respecting exclusions."""
    if excluded_modules is None:
        excluded_modules = []

    files: list[Path] = []
    for py_file in sorted(module_path.rglob("*.py")):
        rel = str(py_file)
        if any(fnmatch.fnmatch(rel, pattern) for pattern in excluded_modules):
            continue
        files.append(py_file)
    return files
