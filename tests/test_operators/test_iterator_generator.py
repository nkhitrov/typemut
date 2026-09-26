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
            ["Iterable[int]"],
            id="Iterator->Iterable",
        ),
        pytest.param(
            "x: Generator[int, None, None]\n",
            ["Iterator[int]"],
            id="Generator->Iterator",
        ),
        pytest.param(
            "x: AsyncIterator[int]\n",
            ["AsyncIterable[int]"],
            id="AsyncIterator->AsyncIterable",
        ),
        pytest.param(
            "x: AsyncGenerator[int, None]\n",
            ["AsyncIterator[int]"],
            id="AsyncGenerator->AsyncIterator",
        ),
        pytest.param(
            "x: Generator[int, str, bool]\n",
            ["Iterator[int]"],
            id="Generator-with-send-and-return->Iterator",
        ),
        pytest.param(
            "x: Iterator\n",
            ["Iterable"],
            id="bare-Iterator->Iterable",
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
        pytest.param("x: Iterable[int]\n", id="Iterable-no-narrowing"),
        pytest.param("x: AsyncIterable[int]\n", id="AsyncIterable-no-narrowing"),
    ],
)
def test_no_swap(source: str) -> None:
    assert_mutations(source, SwapIteratorGenerator, expected=[])

