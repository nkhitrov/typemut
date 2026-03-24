"""Tests for WidenType operator."""

from __future__ import annotations

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
