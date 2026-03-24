"""Tests for TupleEllipsis operator."""

from __future__ import annotations

import pytest

from typemut.operators.tuple_ellipsis import TupleEllipsis

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: tuple[int]\n", ["tuple[int, ...]"], id="add-ellipsis"),
        pytest.param("x: tuple[int, ...]\n", ["tuple[int]"], id="remove-ellipsis"),
        pytest.param("x: Tuple[int]\n", ["Tuple[int, ...]"], id="Tuple-compat"),
    ],
)
def test_tuple_ellipsis(source: str, expected: list[str]) -> None:
    assert_mutations(source, TupleEllipsis, expected=expected)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("x: tuple[int, str]\n", id="fixed-multi-element"),
        pytest.param("x: tuple[()]\n", id="empty-tuple"),
    ],
)
def test_no_tuple_ellipsis(source: str) -> None:
    assert_mutations(source, TupleEllipsis, expected=[])


def test_tuple_empty_trailer() -> None:
    """Empty trailer inner content returns no mutations (line 62)."""
    from typemut.operators.tuple_ellipsis import _process_trailer
    from typemut.operators.base import Mutation
    import parso

    # Parse a tuple annotation to get real nodes
    tree = parso.parse("x: tuple[int]\n")
    trailer = None
    name_node = None
    def find_nodes(node):
        nonlocal trailer, name_node
        if hasattr(node, 'type') and node.type == 'trailer':
            trailer = node
        if hasattr(node, 'value') and node.value == 'tuple':
            name_node = node
        if hasattr(node, 'children'):
            for child in node.children:
                find_nodes(child)
    find_nodes(tree)
    assert trailer is not None and name_node is not None

    # Remove inner content to simulate empty trailer
    original = trailer.children
    trailer.children = [original[0], original[-1]]  # keep [ and ]
    mutations: list[Mutation] = []
    _process_trailer(name_node, trailer, mutations)
    assert len(mutations) == 0
    trailer.children = original


def test_tuple_whitespace_only_content() -> None:
    """Whitespace-only content in trailer returns no mutations (lines 81, 86)."""
    from typemut.operators.tuple_ellipsis import _process_trailer
    from typemut.operators.base import Mutation
    import parso

    tree = parso.parse("x: tuple[int]\n")
    trailer = None
    name_node = None
    def find_nodes(node):
        nonlocal trailer, name_node
        if hasattr(node, 'type') and node.type == 'trailer':
            trailer = node
        if hasattr(node, 'value') and node.value == 'tuple':
            name_node = node
        if hasattr(node, 'children'):
            for child in node.children:
                find_nodes(child)
    find_nodes(tree)
    assert trailer is not None and name_node is not None

    # Replace inner content with a whitespace-only leaf
    original = trailer.children
    # Get the inner node (int) and change its value to whitespace
    inner = original[1]  # the 'int' name
    old_value = inner.value
    inner.value = "  "
    mutations: list[Mutation] = []
    _process_trailer(name_node, trailer, mutations)
    assert len(mutations) == 0
    inner.value = old_value  # restore


def test_tuple_leaf_empty_parens() -> None:
    """tuple[()] Leaf with '()' value returns no mutations (line 100)."""
    from typemut.operators.tuple_ellipsis import _process_trailer
    from typemut.operators.base import Mutation
    import parso

    tree = parso.parse("x: tuple[int]\n")
    trailer = None
    name_node = None
    def find_nodes(node):
        nonlocal trailer, name_node
        if hasattr(node, 'type') and node.type == 'trailer':
            trailer = node
        if hasattr(node, 'value') and node.value == 'tuple':
            name_node = node
        if hasattr(node, 'children'):
            for child in node.children:
                find_nodes(child)
    find_nodes(tree)
    assert trailer is not None and name_node is not None

    # Replace inner content with "()" to simulate tuple[()]
    original = trailer.children
    inner = original[1]
    old_value = inner.value
    inner.value = "()"
    mutations: list[Mutation] = []
    _process_trailer(name_node, trailer, mutations)
    assert len(mutations) == 0
    inner.value = old_value


def test_tuple_empty_parens_source() -> None:
    """tuple[()] returns no mutations via full discovery path."""
    assert_mutations("x: tuple[()]\n", TupleEllipsis, expected=[])
