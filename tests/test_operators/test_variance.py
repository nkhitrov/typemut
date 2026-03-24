"""Tests for TypeVarVariance operator."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.variance import TypeVarVariance
from typemut.registry import Registry


def test_covariant_typevar():
    """TypeVar with covariant=True produces remove and swap mutations."""
    source = 'from typing import TypeVar\nT = TypeVar("T", covariant=True)\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1

    op = TypeVarVariance()
    mutations = op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())

    assert len(mutations) == 2
    # Mutation 1: remove covariant
    assert "covariant" not in mutations[0].mutated
    assert 'TypeVar("T")' in mutations[0].mutated
    # Mutation 2: swap to contravariant
    assert "contravariant=True" in mutations[1].mutated
    assert "covariant" not in mutations[1].mutated.replace("contravariant", "")


def test_contravariant_typevar():
    """TypeVar with contravariant=True produces remove and swap mutations."""
    source = 'from typing import TypeVar\nT = TypeVar("T", contravariant=True)\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1

    op = TypeVarVariance()
    mutations = op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())

    assert len(mutations) == 2
    # Mutation 1: remove contravariant
    assert "contravariant" not in mutations[0].mutated
    assert 'TypeVar("T")' in mutations[0].mutated
    # Mutation 2: swap to covariant
    assert "covariant=True" in mutations[1].mutated


def test_invariant_typevar():
    """TypeVar with no variance produces add covariant and add contravariant mutations."""
    source = 'from typing import TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1

    op = TypeVarVariance()
    mutations = op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())

    assert len(mutations) == 2
    assert "covariant=True" in mutations[0].mutated
    assert "contravariant=True" in mutations[1].mutated


def test_typevar_with_bound_preserves_bound():
    """TypeVar with bound=int adds variance while preserving bound."""
    source = 'from typing import TypeVar\nT = TypeVar("T", bound=int)\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1

    op = TypeVarVariance()
    mutations = op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())

    assert len(mutations) == 2
    # Both mutations should preserve bound=int
    assert "bound=int" in mutations[0].mutated
    assert "bound=int" in mutations[1].mutated
    assert "covariant=True" in mutations[0].mutated
    assert "contravariant=True" in mutations[1].mutated


def test_no_typing_import_no_typevar_discovery():
    """TypeVar not imported from typing produces no TypeVar discoveries."""
    source = 'T = TypeVar("T", covariant=True)\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


def test_regular_annotations_alongside_typevar():
    """Regular annotations still work alongside TypeVar discoveries."""
    source = 'from typing import TypeVar\nT = TypeVar("T")\nx: int = 5\n'
    annotations = discover_annotations(Path("test.py"), source=source)

    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    variables = [a for a in annotations if a.context == AnnotationContext.VARIABLE]

    assert len(tvars) == 1
    assert len(variables) == 1
    assert variables[0].code.strip() == "int"


def test_operator_ignores_non_typevar_context():
    """Operator returns empty list for non-TYPEVAR contexts."""
    source = "x: int = 5\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = TypeVarVariance()
    mutations = op.find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert len(mutations) == 0
