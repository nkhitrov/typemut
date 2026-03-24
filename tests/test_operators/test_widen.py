"""Tests for WidenContainerType operator."""

from __future__ import annotations

import pytest

from typemut.operators.widen import WidenContainerType

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: list[int]\n", ["Sequence[int]"], id="list->Sequence"),
        pytest.param("x: set[int]\n", ["AbstractSet[int]"], id="set->AbstractSet"),
        pytest.param("x: dict[str, int]\n", ["Mapping[str, int]"], id="dict->Mapping"),
        pytest.param("x: Sequence[int]\n", ["Collection[int]"], id="Sequence->Collection"),
        pytest.param("x: Collection[int]\n", ["Iterable[int]"], id="Collection->Iterable"),
        pytest.param("x: tuple[int, str]\n", ["Sequence[int, str]"], id="tuple->Sequence"),
        pytest.param("x: list\n", ["Sequence"], id="bare-list->Sequence"),
    ],
)
def test_widen_container(source: str, expected: list[str]) -> None:
    assert_mutations(source, WidenContainerType, expected=expected)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("x: Iterable[int]\n", id="Iterable-no-widen"),
        pytest.param("x: int\n", id="plain-type-no-widen"),
    ],
)
def test_no_widen(source: str) -> None:
    assert_mutations(source, WidenContainerType, expected=[])
