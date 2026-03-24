"""Tests for SwapContainerType operator."""

from __future__ import annotations

import pytest

from typemut.operators.container import SwapContainerType

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: list[int]\n", ["tuple[int]"], id="list->tuple"),
        pytest.param("x: set[str]\n", ["frozenset[str]"], id="set->frozenset"),
    ],
)
def test_swap_container(source: str, expected: list[str]) -> None:
    assert_mutations(source, SwapContainerType, expected=expected)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("x: dict[str, int]\n", id="dict-no-swap"),
        pytest.param("x: int\n", id="plain-type-no-swap"),
    ],
)
def test_no_swap(source: str) -> None:
    assert_mutations(source, SwapContainerType, expected=[])
