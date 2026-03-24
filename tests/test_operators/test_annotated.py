"""Tests for StripAnnotated operator."""

from __future__ import annotations

import pytest

from typemut.operators.annotated import StripAnnotated

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
