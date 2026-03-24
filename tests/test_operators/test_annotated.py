"""Tests for StripAnnotated operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.annotated import StripAnnotated
from typemut.registry import Registry

from tests.conftest import assert_mutations


def test_strip_annotated() -> None:
    source = 'from typing import Annotated\nx: Annotated[str, "metadata"]\n'
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["str"],
        annotation_filter="Annotated",
    )
    assert "StripAnnotated" in mutations[0].operator


def test_no_strip_for_plain_type() -> None:
    assert_mutations("x: int\n", StripAnnotated, expected=[])


def test_strip_annotated_with_complex_type_and_metadata() -> None:
    source = 'from typing import Annotated\nx: Annotated[list[int], "metadata"]\n'
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["list[int]"],
        annotation_filter="Annotated",
    )
    assert mutations[0].operator == "StripAnnotated"


def test_strip_annotated_complex_type_no_metadata() -> None:
    source = "from typing import Annotated\nx: Annotated[list[int]]\n"
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["list[int]"],
        annotation_filter="Annotated",
    )
    assert mutations[0].operator == "StripAnnotated"


def test_strip_annotated_no_metadata() -> None:
    source = "from typing import Annotated\nx: Annotated[str]\n"
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["str"],
        annotation_filter="Annotated",
    )
    assert len(mutations) == 1


def test_non_annotated_recurse() -> None:
    source = 'from typing import Annotated\nx: list[Annotated[str, "meta"]]\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    op = StripAnnotated()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 1
    assert mutations[0].mutated == "str"
