"""Tests for SwapSiblingType operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.sibling import SwapSiblingType
from typemut.registry import Registry


def test_swap_sibling():
    source = "state: ActiveLoan\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1

    reg = Registry()
    reg.hierarchy = {"LoanState": ["ActiveLoan", "ClosedLoan", "OverdueLoan"]}
    reg.class_to_base = {
        "ActiveLoan": "LoanState",
        "ClosedLoan": "LoanState",
        "OverdueLoan": "LoanState",
    }

    op = SwapSiblingType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, reg)

    assert len(mutations) == 2
    mutated = {m.mutated for m in mutations}
    assert "ClosedLoan" in mutated
    assert "OverdueLoan" in mutated


def test_no_swap_for_unknown_class():
    source = "x: SomeUnknown\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    reg = Registry()
    op = SwapSiblingType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, reg)
    assert len(mutations) == 0
