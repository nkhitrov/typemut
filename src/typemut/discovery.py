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
        if hasattr(child, "value") and child.value == "->":
            if i + 1 < len(children):
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
    if isinstance(node, Leaf) and node.value == "Any":
        return True
    return False


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

    def visit(node: BaseNode | Leaf) -> None:
        if isinstance(node, BaseNode):
            # Variable annotation: x: int
            if node.type == "annassign":
                ann = _get_annotation_from_annassign(node)
                if ann is not None and not _is_any(ann):
                    line = ann.start_pos[0]
                    if not _should_skip_line(
                        _line_text(file_lines, line), skip_comments
                    ):
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
                    if not _should_skip_line(
                        _line_text(file_lines, line), skip_comments
                    ):
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
                    if not _should_skip_line(
                        _line_text(file_lines, line), skip_comments
                    ):
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
