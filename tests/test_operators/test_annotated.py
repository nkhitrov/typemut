"""Tests for StripAnnotated operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.annotated import StripAnnotated
from typemut.registry import Registry


def test_strip_annotated():
    source = 'from typing import Annotated\nx: Annotated[str, "metadata"]\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    ann = [a for a in annotations if "Annotated" in a.code]
    assert len(ann) == 1

    op = StripAnnotated()
    mutations = op.find_mutations(ann[0].node, AnnotationContext.VARIABLE, Registry())

    assert len(mutations) == 1
    assert mutations[0].mutated == "str"
    assert "StripAnnotated" in mutations[0].operator


def test_no_strip_for_plain_type():
    source = "x: int\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = StripAnnotated()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 0
