"""Tests for WidenContainerType operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.widen import WidenContainerType
from typemut.registry import Registry


def test_widen_list_to_sequence():
    source = "x: list[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Sequence[int]"


def test_widen_set_to_abstractset():
    source = "x: set[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "AbstractSet[int]"


def test_widen_dict_to_mapping():
    source = "x: dict[str, int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Mapping[str, int]"


def test_widen_sequence_to_collection():
    source = "x: Sequence[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Collection[int]"


def test_widen_collection_to_iterable():
    source = "x: Collection[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Iterable[int]"


def test_no_widen_for_iterable():
    source = "x: Iterable[int]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 0


def test_widen_tuple_to_sequence():
    source = "x: tuple[int, str]\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Sequence[int, str]"


def test_widen_bare_list():
    source = "x: list\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "Sequence"


def test_no_widen_for_plain_type():
    source = "x: int\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = WidenContainerType()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 0
