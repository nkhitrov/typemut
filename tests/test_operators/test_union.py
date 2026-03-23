"""Tests for RemoveUnionMember operator."""

from __future__ import annotations

from pathlib import Path

import parso

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.union import RemoveUnionMember
from typemut.registry import Registry


def _get_annotation_node(source: str, index: int = 0):
    annotations = discover_annotations(Path("test.py"), source=source)
    return annotations[index].node


def test_remove_from_triple_union():
    source = "x: int | str | float\n"
    node = _get_annotation_node(source)
    op = RemoveUnionMember()
    mutations = op.find_mutations(node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 3
    mutated_texts = {m.mutated for m in mutations}
    assert "str | float" in mutated_texts
    assert "int | float" in mutated_texts
    assert "int | str" in mutated_texts


def test_remove_from_binary_union():
    source = "x: int | str\n"
    node = _get_annotation_node(source)
    op = RemoveUnionMember()
    mutations = op.find_mutations(node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 2
    mutated_texts = {m.mutated for m in mutations}
    assert "str" in mutated_texts
    assert "int" in mutated_texts


def test_skip_none_removal():
    source = "x: int | None\n"
    node = _get_annotation_node(source)
    op = RemoveUnionMember()
    mutations = op.find_mutations(node, AnnotationContext.VARIABLE, Registry())

    # Should only generate removing int (None removal is for RemoveOptional)
    assert len(mutations) == 1
    assert mutations[0].mutated == "None"


def test_no_mutation_for_simple_type():
    source = "x: int\n"
    node = _get_annotation_node(source)
    op = RemoveUnionMember()
    mutations = op.find_mutations(node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0
