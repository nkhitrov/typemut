"""Tests for WidenType operator."""

from __future__ import annotations

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
