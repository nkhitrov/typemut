"""Tests for WidenType operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.widen_type import WidenType
from typemut.registry import Registry


def test_widen_type():
    source = "pet: Cat\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1

    reg = Registry()
    reg.hierarchy = {"Animal": ["Cat", "Dog"]}
    reg.class_to_base = {
        "Cat": "Animal",
        "Dog": "Animal",
    }

    op = WidenType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, reg)

    assert len(mutations) == 1
    assert mutations[0].mutated == "Animal"
    assert mutations[0].original == "Cat"


def test_no_widen_for_unknown_class():
    source = "x: SomeUnknown\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    reg = Registry()
    op = WidenType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, reg)
    assert len(mutations) == 0
