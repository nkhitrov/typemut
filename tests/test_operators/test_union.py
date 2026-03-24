"""Tests for RemoveUnionMember operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.union import RemoveUnionMember
from typemut.registry import Registry


def _get_mutations(source: str):
    annotations = discover_annotations(Path("test.py"), source=source)
    op = RemoveUnionMember()
    return op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())


def test_remove_from_triple_union() -> None:
    mutations = _get_mutations("x: int | str | float\n")
    assert len(mutations) == 3
    mutated = {m.mutated for m in mutations}
    assert mutated == {"str | float", "int | float", "int | str"}


def test_remove_from_binary_union() -> None:
    mutations = _get_mutations("x: int | str\n")
    assert len(mutations) == 2
    mutated = {m.mutated for m in mutations}
    assert mutated == {"str", "int"}


def test_skip_none_removal() -> None:
    mutations = _get_mutations("x: int | None\n")
    assert len(mutations) == 1
    assert mutations[0].mutated == "None"


def test_no_mutation_for_simple_type() -> None:
    mutations = _get_mutations("x: int\n")
    assert len(mutations) == 0
