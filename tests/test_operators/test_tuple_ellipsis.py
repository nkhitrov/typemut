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
