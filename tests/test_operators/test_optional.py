"""Tests for RemoveOptional and AddOptional operators."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.optional import AddOptional, RemoveOptional
from typemut.registry import Registry


def test_remove_optional():
    source = "x: int | None\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = RemoveOptional()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "int"


def test_remove_optional_with_multiple():
    source = "x: int | str | None\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = RemoveOptional()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "int | str"


def test_no_remove_optional_without_none():
    source = "x: int | str\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = RemoveOptional()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0


def test_add_optional():
    source = "x: int\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = AddOptional()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "int | None"


def test_add_optional_skips_already_optional():
    source = "x: int | None\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = AddOptional()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0


def test_add_optional_skips_parameters():
    source = "def f(x: int) -> str:\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = AddOptional()
    param_ann = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    ret_ann = [a for a in annotations if a.context == AnnotationContext.RETURN]

    # Parameters should be skipped
    assert len(param_ann) == 1
    mutations = op.find_mutations(param_ann[0].node, AnnotationContext.PARAMETER, Registry())
    assert len(mutations) == 0

    # Return type should still work
    assert len(ret_ann) == 1
    mutations = op.find_mutations(ret_ann[0].node, AnnotationContext.RETURN, Registry())
    assert len(mutations) == 1
    assert mutations[0].mutated == "str | None"
