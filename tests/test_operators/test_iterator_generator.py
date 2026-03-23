"""Tests for SwapIteratorGenerator operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.iterator_generator import SwapIteratorGenerator
from typemut.registry import Registry


def test_iterator_to_generator_and_iterable():
    source = "x: Iterator[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 2
    mutated_texts = {m.mutated for m in mutations}
    assert "Generator[int, None, None]" in mutated_texts
    assert "Iterable[int]" in mutated_texts


def test_generator_to_iterator():
    source = "x: Generator[int, None, None]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Iterator[int]"


def test_async_iterator_to_async_generator_and_iterable():
    source = "x: AsyncIterator[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 2
    mutated_texts = {m.mutated for m in mutations}
    assert "AsyncGenerator[int, None]" in mutated_texts
    assert "AsyncIterable[int]" in mutated_texts


def test_async_generator_to_async_iterator():
    source = "x: AsyncGenerator[int, None]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "AsyncIterator[int]"


def test_iterable_to_iterator():
    source = "x: Iterable[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Iterator[int]"


def test_bare_iterator():
    source = "x: Iterator\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 2
    mutated_texts = {m.mutated for m in mutations}
    assert "Generator" in mutated_texts
    assert "Iterable" in mutated_texts


def test_bare_generator():
    source = "x: Generator\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Iterator"


def test_no_swap_for_list():
    source = "x: list[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0


def test_no_swap_for_dict():
    source = "x: dict[str, int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = SwapIteratorGenerator()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0
