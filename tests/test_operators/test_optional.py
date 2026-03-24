"""Tests for RemoveOptional and AddOptional operators."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.optional import AddOptional, RemoveOptional
from typemut.registry import Registry

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: int | None\n", ["int"], id="simple-optional"),
        pytest.param("x: int | str | None\n", ["int | str"], id="multi-optional"),
    ],
)
def test_remove_optional(source: str, expected: list[str]) -> None:
    assert_mutations(source, RemoveOptional, expected=expected)


def test_no_remove_optional_without_none() -> None:
    assert_mutations("x: int | str\n", RemoveOptional, expected=[])


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: int\n", ["int | None"], id="add-optional"),
    ],
)
def test_add_optional(source: str, expected: list[str]) -> None:
    assert_mutations(source, AddOptional, expected=expected)


def test_add_optional_skips_already_optional() -> None:
    assert_mutations("x: int | None\n", AddOptional, expected=[])


def test_add_optional_skips_parameters() -> None:
    source = "def f(x: int) -> str:\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = AddOptional()
    param_ann = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    ret_ann = [a for a in annotations if a.context == AnnotationContext.RETURN]

    assert len(param_ann) == 1
    mutations = op.find_mutations(param_ann[0].node, AnnotationContext.PARAMETER, Registry())
    assert len(mutations) == 0

    assert len(ret_ann) == 1
    mutations = op.find_mutations(ret_ann[0].node, AnnotationContext.RETURN, Registry())
    assert len(mutations) == 1
    assert mutations[0].mutated == "str | None"


def test_remove_optional_non_union() -> None:
    """RemoveOptional on a plain type returns empty (line 24, 110)."""
    assert_mutations("x: int\n", RemoveOptional, expected=[])


def test_remove_optional_non_expr_basenode() -> None:
    """RemoveOptional on a BaseNode that's not expr/arith_expr (line 112)."""
    # list[int] is a power/atom_expr node, not expr/arith_expr
    assert_mutations("x: list[int]\n", RemoveOptional, expected=[])


def test_remove_optional_all_none() -> None:
    """Union of only None members returns empty (line 36)."""
    # This tests the edge case where all non-None members are removed
    # In practice, a union of only None is unusual but the code handles it
    from typemut.operators.optional import _extract_union_members
    source = "x: None | None\n"
    # RemoveOptional: all members are None, so remaining is empty
    annotations = discover_annotations(Path("test.py"), source=source)
    if annotations:
        op = RemoveOptional()
        mutations = op.find_mutations(
            annotations[0].node, AnnotationContext.VARIABLE, Registry()
        )
        assert len(mutations) == 0


def test_add_optional_skips_self() -> None:
    """AddOptional skips 'self' parameter (line 74)."""
    import parso
    tree = parso.parse("self\n")
    # Get the 'self' name node
    node = tree.children[0].children[0]  # simple_stmt -> expr_stmt or name
    if hasattr(node, 'children'):
        node = node.children[0]
    assert node.value == "self"
    op = AddOptional()
    mutations = op.find_mutations(node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0


def test_add_optional_skips_none() -> None:
    """AddOptional skips None type (line 84)."""
    from unittest.mock import patch
    import parso
    tree = parso.parse("None\n")
    node = tree.children[0].children[0]
    if hasattr(node, 'children'):
        node = node.children[0]
    assert node.value == "None"
    op = AddOptional()
    # Patch _contains_none to return False, so we reach the code == "None" check
    with patch("typemut.operators.optional._contains_none", return_value=False):
        mutations = op.find_mutations(node, AnnotationContext.RETURN, Registry())
    assert len(mutations) == 0


def test_extract_union_arith_expr() -> None:
    """_extract_union_members handles arith_expr type (line 112)."""
    from typemut.operators.optional import _extract_union_members
    import parso
    from parso.python.tree import PythonNode

    # Parse a union to get real nodes, then change node type to arith_expr
    tree = parso.parse("x: int | str\n")
    # Find the expr node
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

    # Wrap in a PythonNode with arith_expr type
    fake = PythonNode("arith_expr", list(expr.children))
    members = _extract_union_members(fake)
    assert len(members) == 2


def test_extract_union_no_pipe() -> None:
    """_extract_union_members with no pipe returns empty (line 117)."""
    from typemut.operators.optional import _extract_union_members
    from parso.python.tree import PythonNode
    import parso

    # Parse something that looks like an expr but has no pipe
    tree = parso.parse("x + y\n")
    # Find expr node
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
    if expr is not None:
        # It has + not |, so no pipe
        members = _extract_union_members(expr)
        assert len(members) == 0
    else:
        # If parso doesn't create expr for x+y, create one manually
        tree2 = parso.parse("x: int | str\n")
        find_expr(tree2)
        assert expr is not None
        fake = PythonNode("expr", [expr.children[0]])  # only one child, no pipe
        members = _extract_union_members(fake)
        assert len(members) == 0
