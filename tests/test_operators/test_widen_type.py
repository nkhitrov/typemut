"""Tests for WidenType operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.operators.widen_type import WidenType
from typemut.registry import Registry

from tests.conftest import assert_mutations


def test_widen_type() -> None:
    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat", "Dog"]}
    reg.class_to_base = {"Cat": "Animal", "Dog": "Animal"}

    assert_mutations("pet: Cat\n", WidenType, expected=["Animal"], registry=reg)


def test_no_widen_for_unknown_class() -> None:
    assert_mutations("x: SomeUnknown\n", WidenType, expected=[])


def test_widen_type_in_complex_annotation() -> None:
    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat"]}
    reg.class_to_base = {"Cat": "Animal"}

    assert_mutations("pets: list[Cat]\n", WidenType, expected=["Animal"], registry=reg)


@pytest.mark.parametrize(
    "base",
    ["object", "ABC", "Generic", "Protocol", "NamedTuple", "TypedDict"],
)
def test_no_widen_to_interfaceless_base(base: str) -> None:
    reg = Registry()
    reg.hierarchy = {base: ["Child"]}
    reg.class_to_base = {"Child": base}

    assert_mutations("x: Child\n", WidenType, expected=[], registry=reg)


def test_no_widen_qualified_name() -> None:
    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat"]}
    reg.class_to_base = {"Cat": "Animal"}

    assert_mutations("x: models.Cat\n", WidenType, expected=[], registry=reg)


@pytest.mark.parametrize("protocol_base", ["Protocol[A, B]", "Protocol"])
def test_no_widen_to_protocol_from_files(tmp_path: Path, protocol_base: str) -> None:
    """Regression test for #14: a Protocol base must not be a WidenType target."""
    src = tmp_path / "serialization.py"
    src.write_text(
        "from typing import Protocol, TypeVar\n"
        "\n"
        "A = TypeVar('A')\n"
        "B = TypeVar('B')\n"
        "\n"
        f"class Coder({protocol_base}):\n"
        "    def encode(self, value: A) -> B: ...\n"
    )
    reg = Registry.from_files([src])

    assert_mutations("c: Coder\n", WidenType, expected=[], registry=reg)
