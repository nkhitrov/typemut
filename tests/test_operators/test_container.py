"""Tests for SwapContainerType operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.container import SwapContainerType
from typemut.registry import Registry


def test_swap_list_to_tuple():
    source = "x: list[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert "tuple[int]" in mutations[0].mutated


def test_swap_set_to_frozenset():
    source = "x: set[str]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert "frozenset[str]" in mutations[0].mutated


def test_no_swap_for_dict():
    source = "x: dict[str, int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0


def test_no_swap_for_plain_type():
    source = "x: int\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0
