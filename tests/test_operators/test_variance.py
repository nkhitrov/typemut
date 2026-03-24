"""Tests for TypeVarVariance operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.variance import TypeVarVariance
from typemut.registry import Registry


def _get_typevar_mutations(source: str):
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    op = TypeVarVariance()
    return op.find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())


def test_covariant_typevar() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T", covariant=True)\n'
    )
    assert len(mutations) == 2
    assert "covariant" not in mutations[0].mutated
    assert 'TypeVar("T")' in mutations[0].mutated
    assert "contravariant=True" in mutations[1].mutated


def test_contravariant_typevar() -> None:
    mutations = _get_typevar_mutations(
        'from typing import TypeVar\nT = TypeVar("T", contravariant=True)\n'
    )
    assert len(mutations) == 2
    assert "contravariant" not in mutations[0].mutated
    assert 'TypeVar("T")' in mutations[0].mutated
    assert "covariant=True" in mutations[1].mutated


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


def test_no_typing_import_no_typevar_discovery() -> None:
    source = 'T = TypeVar("T", covariant=True)\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


def test_regular_annotations_alongside_typevar() -> None:
    source = 'from typing import TypeVar\nT = TypeVar("T")\nx: int = 5\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    variables = [a for a in annotations if a.context == AnnotationContext.VARIABLE]
    assert len(tvars) == 1
    assert len(variables) == 1
    assert variables[0].code.strip() == "int"


def test_operator_ignores_non_typevar_context() -> None:
    source = "x: int = 5\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    op = TypeVarVariance()
    mutations = op.find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert len(mutations) == 0


def test_no_args_trailer() -> None:
    """TypeVar node with no args trailer returns no mutations (line 27)."""
    import parso
    from typemut.operators.variance import TypeVarVariance

    # Parse a TypeVar and remove the trailer to simulate missing args
    source = 'from typing import TypeVar\nT = TypeVar("T")\n'
    tree = parso.parse(source)

    # Find the TypeVar atom_expr node and remove its trailer
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1

    node = tvars[0].node
    original_children = node.children
    node.children = [original_children[0]]  # only keep the Name, remove trailer

    op = TypeVarVariance()
    mutations = op.find_mutations(node, AnnotationContext.TYPEVAR, Registry())
    assert len(mutations) == 0
    node.children = original_children  # restore


def test_find_args_trailer_no_paren() -> None:
    """_find_args_trailer returns None when trailer doesn't start with '(' (line 130)."""
    from typemut.operators.variance import _find_args_trailer
    import parso

    # Parse a subscript to get a trailer that starts with '[' not '('
    tree = parso.parse("x: list[int]\n")
    trailer = None
    def find_trailer(node):
        nonlocal trailer
        if hasattr(node, 'type') and node.type == 'trailer':
            trailer = node
            return
        if hasattr(node, 'children'):
            for child in node.children:
                find_trailer(child)
    find_trailer(tree)
    assert trailer is not None

    # Wrap in a parent BaseNode
    from parso.python.tree import PythonNode
    parent = PythonNode("power", [trailer])
    assert _find_args_trailer(parent) is None


def test_remove_kwarg_trailing_pattern() -> None:
    """_remove_kwarg uses trailing comma pattern (lines 151-152)."""
    from typemut.operators.variance import _remove_kwarg

    # Pattern where kwarg is first, followed by trailing comma
    # This triggers the second regex pattern (kwarg=True, )
    text = 'TypeVar(covariant=True, "T")'
    result = _remove_kwarg(text, "covariant")
    assert "covariant" not in result
    assert '"T"' in result


def test_add_kwarg_no_closing_paren() -> None:
    """_add_kwarg with no closing paren returns text unchanged (line 165)."""
    from typemut.operators.variance import _add_kwarg

    text = 'TypeVar("T"'
    result = _add_kwarg(text, "covariant=True")
    assert result == text


def test_add_kwarg_no_opening_paren() -> None:
    """_add_kwarg with no opening paren returns text unchanged (line 169)."""
    from typemut.operators.variance import _add_kwarg

    text = 'TypeVar"T")'
    result = _add_kwarg(text, "covariant=True")
    assert result == text


def test_add_kwarg_empty_parens() -> None:
    """_add_kwarg with empty parens adds without comma (line 174)."""
    from typemut.operators.variance import _add_kwarg

    text = "TypeVar()"
    result = _add_kwarg(text, "covariant=True")
    assert result == "TypeVar(covariant=True)"
