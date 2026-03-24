"""Tests for RemoveUnionMember operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.union import RemoveUnionMember
from typemut.registry import Registry


def _get_mutations(source: str):
    annotations = discover_annotations(Path("test.py"), source=source)
    op = RemoveUnionMember()
    return op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())


def test_remove_from_triple_union() -> None:
    mutations = _get_mutations("x: int | str | float\n")
    assert len(mutations) == 3
    mutated = {m.mutated for m in mutations}
    assert mutated == {"str | float", "int | float", "int | str"}


def test_remove_from_binary_union() -> None:
    mutations = _get_mutations("x: int | str\n")
    assert len(mutations) == 2
    mutated = {m.mutated for m in mutations}
    assert mutated == {"str", "int"}


def test_skip_none_removal() -> None:
    mutations = _get_mutations("x: int | None\n")
    assert len(mutations) == 1
    assert mutations[0].mutated == "None"


def test_no_mutation_for_simple_type() -> None:
    mutations = _get_mutations("x: int\n")
    assert len(mutations) == 0


def test_extract_union_non_expr_basenode() -> None:
    """_extract_union_members returns empty for non-expr BaseNode (line 64)."""
    from typemut.operators.union import _extract_union_members

    # list[int] is an atom_expr BaseNode, not expr/arith_expr
    annotations = discover_annotations(Path("test.py"), source="x: list[int]\n")
    op = RemoveUnionMember()
    mutations = op.find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert len(mutations) == 0


def test_extract_union_no_pipe() -> None:
    """_extract_union_members returns empty if no pipe operator (line 70)."""
    from typemut.operators.union import _extract_union_members
    from parso.python.tree import PythonNode
    import parso

    tree = parso.parse("x: int | str\n")
    expr = None
    def find_expr(node):
        nonlocal expr
        if hasattr(node, 'type') and node.type in ('expr', 'arith_expr'):
            expr = node
            return
        if hasattr(node, 'children'):
            for child in node.children:
                find_expr(child)
    find_expr(tree)
    assert expr is not None

    # Create expr node with no pipe
    fake = PythonNode("expr", [expr.children[0]])
    members = _extract_union_members(fake)
    assert len(members) == 0
