"""Tests for TypeVarVariance operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.model import AnnotationContext
from typemut.operators.variance import TypeVarVariance
from typemut.registry import Registry


def _get_typevar_mutations(source: str):
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    op = TypeVarVariance()
    return op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())


def test_covariant_typevar() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T", covariant=True)\n'
    )
    assert [m.mutated for m in mutations] == ['TypeVar("T")']


def test_contravariant_typevar() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T", contravariant=True)\n'
    )
    assert [m.mutated for m in mutations] == ['TypeVar("T")']


def test_invariant_typevar() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T")\n'
    )
    assert len(mutations) == 2
    assert "covariant=True" in mutations[0].mutated
    assert "contravariant=True" in mutations[1].mutated


def test_typevar_with_bound_preserves_bound() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T", bound=int)\n'
    )
    assert len(mutations) == 2
    for m in mutations:
        assert "bound=int" in m.mutated
    assert "covariant=True" in mutations[0].mutated
    assert "contravariant=True" in mutations[1].mutated


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        pytest.param(
            'TypeVar("T", bound=int,)',
            [
                'TypeVar("T", bound=int, covariant=True,)',
                'TypeVar("T", bound=int, contravariant=True,)',
            ],
            id="trailing-comma",
        ),
        pytest.param(
            'TypeVar(\n    "T",\n    bound=int,\n)',
            [
                'TypeVar(\n    "T",\n    bound=int, covariant=True,\n)',
                'TypeVar(\n    "T",\n    bound=int, contravariant=True,\n)',
            ],
            id="multi-line-trailing-comma",
        ),
        pytest.param(
            'TypeVar(\n    "T"  # name\n)',
            [
                'TypeVar(\n    "T", covariant=True  # name\n)',
                'TypeVar(\n    "T", contravariant=True  # name\n)',
            ],
            id="comment-before-paren",
        ),
        pytest.param(
            'TypeVar("T", covariant=False)',
            ['TypeVar("T", covariant=False, contravariant=True)'],
            id="explicit-false-not-duplicated",
        ),
        pytest.param(
            'TypeVar("T", infer_variance=True)',
            [],
            id="inferred-variance",
        ),
        pytest.param(
            'TypeVar("T", infer_variance=False)',
            [
                'TypeVar("T", infer_variance=False, covariant=True)',
                'TypeVar("T", infer_variance=False, contravariant=True)',
            ],
            id="variance-not-inferred",
        ),
        pytest.param(
            "TypeVar()",
            ["TypeVar(covariant=True)", "TypeVar(contravariant=True)"],
            id="no-arguments",
        ),
        pytest.param(
            'TypeVar("T", *rest)',
            ['TypeVar("T", *rest, covariant=True)', 'TypeVar("T", *rest, contravariant=True)'],
            id="star-argument",
        ),
    ],
)
def test_add_variance_keeps_call_valid(call: str, expected: list[str]) -> None:
    mutations = _get_typevar_mutations(f"from typing import TypeVar\nT = {call}\n")
    assert [m.mutated for m in mutations] == expected


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        pytest.param(
            'TypeVar("T", covariant=True,)',
            'TypeVar("T",)',
            id="last-trailing-comma",
        ),
        pytest.param(
            'TypeVar(\n    "T",\n    covariant=True,\n)',
            'TypeVar(\n    "T",\n)',
            id="multi-line-last-trailing-comma",
        ),
        pytest.param(
            'TypeVar("T", covariant=True, bound=int)',
            'TypeVar("T", bound=int)',
            id="middle",
        ),
        pytest.param(
            'TypeVar("T", contravariant=True, bound=int)',
            'TypeVar("T", bound=int)',
            id="middle-contravariant",
        ),
        pytest.param(
            'TypeVar(\n    "T",\n    covariant=True,\n    bound=int,\n)',
            'TypeVar(\n    "T",\n    bound=int,\n)',
            id="multi-line-middle",
        ),
        pytest.param(
            'TypeVar("T", covariant = True)',
            'TypeVar("T")',
            id="spaces-around-equals",
        ),
        pytest.param(
            'TypeVar("T", bound=int, covariant=False, contravariant=True)',
            'TypeVar("T", bound=int, covariant=False)',
            id="only-true-flag-removed",
        ),
    ],
)
def test_remove_variance_keeps_call_valid(call: str, expected: str) -> None:
    mutations = _get_typevar_mutations(f"from typing import TypeVar\nT = {call}\n")
    assert [m.mutated for m in mutations] == [expected]


def test_qualified_typevar_trailing_comma() -> None:
    mutations = _get_typevar_mutations(
        'import typing\nT = typing.TypeVar("T",)\n'
    )
    assert [m.mutated for m in mutations] == [
        'typing.TypeVar("T", covariant=True,)',
        'typing.TypeVar("T", contravariant=True,)',
    ]


def test_no_typing_import_no_typevar_discovery() -> None:
    source = 'T = TypeVar("T", covariant=True)\n'
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


def test_regular_annotations_alongside_typevar() -> None:
    source = 'from typing import TypeVar\nT = TypeVar("T")\nx: int = 5\n'
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    variables = [a for a in annotations if a.context == AnnotationContext.VARIABLE]
    assert len(tvars) == 1
    assert len(variables) == 1
    assert variables[0].code.strip() == "int"


def test_operator_ignores_non_typevar_context() -> None:
    source = "x: int = 5\n"
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    op = TypeVarVariance()
    mutations = op.find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert len(mutations) == 0
