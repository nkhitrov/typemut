"""Tests for SwapIteratorGenerator operator."""

from __future__ import annotations

import pytest

from typemut.operators.iterator_generator import SwapIteratorGenerator

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
