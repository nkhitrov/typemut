"""Tests for TupleEllipsis operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.tuple_ellipsis import TupleEllipsis
from typemut.registry import Registry


def test_add_ellipsis():
    source = "x: tuple[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TupleEllipsis()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "tuple[int, ...]"


def test_remove_ellipsis():
    source = "x: tuple[int, ...]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TupleEllipsis()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "tuple[int]"


def test_skip_fixed_multi_element():
    source = "x: tuple[int, str]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TupleEllipsis()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 0


def test_typing_tuple_compat():
    source = "x: Tuple[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TupleEllipsis()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Tuple[int, ...]"


def test_skip_empty_tuple():
    source = "x: tuple[()]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TupleEllipsis()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 0
