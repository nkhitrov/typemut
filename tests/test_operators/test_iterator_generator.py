"""Tests for SwapIteratorGenerator operator."""

from __future__ import annotations

import parso
import pytest

from typemut.operators.iterator_generator import SwapIteratorGenerator, _extract_params

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            "x: Iterator[int]\n",
            ["Generator[int, None, None]", "Iterable[int]"],
            id="Iterator->Generator+Iterable",
        ),
        pytest.param(
            "x: Generator[int, None, None]\n",
            ["Iterator[int]"],
            id="Generator->Iterator",
        ),
        pytest.param(
            "x: AsyncIterator[int]\n",
            ["AsyncGenerator[int, None]", "AsyncIterable[int]"],
            id="AsyncIterator->AsyncGenerator+AsyncIterable",
        ),
        pytest.param(
            "x: AsyncGenerator[int, None]\n",
            ["AsyncIterator[int]"],
            id="AsyncGenerator->AsyncIterator",
        ),
        pytest.param(
            "x: Iterable[int]\n",
            ["Iterator[int]"],
            id="Iterable->Iterator",
        ),
        pytest.param(
            "x: Iterator\n",
            ["Generator", "Iterable"],
            id="bare-Iterator->Generator+Iterable",
        ),
        pytest.param(
            "x: Generator\n",
            ["Iterator"],
            id="bare-Generator->Iterator",
        ),
    ],
)
def test_swap_iterator_generator(source: str, expected: list[str]) -> None:
    assert_mutations(source, SwapIteratorGenerator, expected=expected)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("x: list[int]\n", id="list-no-swap"),
        pytest.param("x: dict[str, int]\n", id="dict-no-swap"),
    ],
)
def test_no_swap(source: str) -> None:
    assert_mutations(source, SwapIteratorGenerator, expected=[])


def test_async_iterable_subscripted() -> None:
    """AsyncIterable[Y] -> AsyncIterator[Y] (lines 190-193)."""
    assert_mutations(
        "x: AsyncIterable[int]\n",
        SwapIteratorGenerator,
        expected=["AsyncIterator[int]"],
    )


def test_empty_trailer_params() -> None:
    """Empty trailer returns empty params list (line 74)."""
    # Parse a subscript expression to get a real trailer node, then empty it
    tree = parso.parse("x: Iterator[int]\n")
    # Find the trailer node
    trailer = None
    def find_trailer(node):
        nonlocal trailer
        if hasattr(node, 'type') and node.type == 'trailer':
            trailer = node
            return
        if hasattr(node, 'children'):
            for child in node.children:
                find_trailer(child)
    find_trailer(tree)
    assert trailer is not None

    # Remove inner content (keep only [ and ])
    original = trailer.children
    trailer.children = [original[0], original[-1]]
    assert _extract_params(trailer) == []
    trailer.children = original  # restore
