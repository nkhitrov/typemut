"""Tests for RemoveLiteralMember operator."""

from __future__ import annotations

import pytest

from typemut.operators.literal import RemoveLiteralMember

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            'x: Literal["a", "b"]\n',
            ['Literal["b"]', 'Literal["a"]'],
            id="two-strings",
        ),
        pytest.param(
            'x: Literal["a", "b", "c"]\n',
            ['Literal["b", "c"]', 'Literal["a", "c"]', 'Literal["a", "b"]'],
            id="three-strings",
        ),
        pytest.param(
            "x: Literal[10, 1, -1]\n",
            ["Literal[1, -1]", "Literal[10, -1]", "Literal[10, 1]"],
            id="numbers-prefix-safe",
        ),
        pytest.param(
            "x: typing.Literal[Color.RED, None]\n",
            ["typing.Literal[None]", "typing.Literal[Color.RED]"],
            id="qualified-enum-and-none",
        ),
        pytest.param(
            'x: list[Literal["r", "w"]] | None\n',
            ['list[Literal["w"]] | None', 'list[Literal["r"]] | None'],
            id="nested-in-container",
        ),
        pytest.param(
            'x: Literal["a", "b"] | Literal[1, 2]\n',
            [
                'Literal["b"] | Literal[1, 2]',
                'Literal["a"] | Literal[1, 2]',
                'Literal["a", "b"] | Literal[2]',
                'Literal["a", "b"] | Literal[1]',
            ],
            id="two-literals",
        ),
    ],
)
def test_remove_literal_member(source: str, expected: list[str]) -> None:
    assert_mutations(source, RemoveLiteralMember, expected=expected)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('x: Literal["a"]\n', id="single-value"),
        pytest.param("x: list[int]\n", id="not-literal"),
        pytest.param("x: int\n", id="plain-name"),
    ],
)
def test_no_remove_literal_member(source: str) -> None:
    assert_mutations(source, RemoveLiteralMember, expected=[])
