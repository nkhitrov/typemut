"""Tests for WidenType operator."""

from __future__ import annotations

from typemut.operators.widen_type import WidenType
from typemut.registry import Registry

from tests.conftest import assert_mutations


def test_widen_type() -> None:
    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat", "Dog"]}
    reg.class_to_base = {"Cat": "Animal", "Dog": "Animal"}

    mutations = assert_mutations(
        "pet: Cat\n", WidenType, expected=["Animal"], registry=reg
    )
    assert mutations[0].original == "Cat"


def test_no_widen_for_unknown_class() -> None:
    assert_mutations("x: SomeUnknown\n", WidenType, expected=[])


def test_widen_type_in_complex_annotation() -> None:
    """WidenType recurses into BaseNode children (lines 54-56)."""
    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat"]}
    reg.class_to_base = {"Cat": "Animal"}

    # Cat inside a subscript like list[Cat]
    mutations = assert_mutations(
        "pets: list[Cat]\n", WidenType, expected=["Animal"], registry=reg
    )
    assert mutations[0].original == "Cat"
    assert mutations[0].mutated == "Animal"
