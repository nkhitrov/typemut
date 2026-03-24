"""Tests for SwapLiteralValue operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.literal import SwapLiteralValue
from typemut.registry import Registry


def test_swap_literal_string():
    source = 'from typing import Literal\nstatus: Literal["active"]\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    # Find the annotation with Literal
    ann = [a for a in annotations if "Literal" in a.code]
    assert len(ann) == 1

    reg = Registry()
    reg.literal_pool = {'"active"', '"closed"', '"overdue"'}

    op = SwapLiteralValue()
    mutations = op.find_mutations(ann[0].node, AnnotationContext.VARIABLE, reg)

    assert len(mutations) == 2
    descriptions = {m.description for m in mutations}
    assert any("closed" in d for d in descriptions)
    assert any("overdue" in d for d in descriptions)


def test_no_swap_without_pool():
    source = 'from typing import Literal\nstatus: Literal["active"]\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    ann = [a for a in annotations if "Literal" in a.code]

    reg = Registry()
    reg.literal_pool = {'"active"'}  # Only one value, no swap possible

    op = SwapLiteralValue()
    mutations = op.find_mutations(ann[0].node, AnnotationContext.VARIABLE, reg)
    assert len(mutations) == 0


def test_swap_literal_multiple_values():
    source = 'from typing import Literal\nstatus: Literal["active", "closed"]\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    ann = [a for a in annotations if "Literal" in a.code]
    assert len(ann) == 1

    reg = Registry()
    reg.literal_pool = {'"active"', '"closed"', '"pending"'}

    op = SwapLiteralValue()
    mutations = op.find_mutations(ann[0].node, AnnotationContext.VARIABLE, reg)
    # Each literal value can be swapped with each other value in pool
    assert len(mutations) > 0
    # Verify at least one swap happened
    mutated_set = {m.mutated for m in mutations}
    assert any('"pending"' in m for m in mutated_set)
