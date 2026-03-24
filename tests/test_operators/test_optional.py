"""Tests for RemoveOptional and AddOptional operators."""

from __future__ import annotations

from pathlib import Path
import pytest

from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.optional import AddOptional, RemoveOptional
from typemut.registry import Registry

from tests.conftest import assert_mutations


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: int | None\n", ["int"], id="simple-optional"),
        pytest.param("x: int | str | None\n", ["int | str"], id="multi-optional"),
    ],
)
def test_remove_optional(source: str, expected: list[str]) -> None:
    assert_mutations(source, RemoveOptional, expected=expected)


def test_no_remove_optional_without_none() -> None:
    assert_mutations("x: int | str\n", RemoveOptional, expected=[])


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: int\n", ["int | None"], id="add-optional"),
    ],
)
def test_add_optional(source: str, expected: list[str]) -> None:
    assert_mutations(source, AddOptional, expected=expected)


def test_add_optional_skips_already_optional() -> None:
    assert_mutations("x: int | None\n", AddOptional, expected=[])


def test_add_optional_skips_parameters() -> None:
    source = "def f(x: int) -> str:\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)

    op = AddOptional()
    param_ann = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    ret_ann = [a for a in annotations if a.context == AnnotationContext.RETURN]

    assert len(param_ann) == 1
    mutations = op.find_mutations(param_ann[0].node, AnnotationContext.PARAMETER, Registry())
    assert len(mutations) == 0

    assert len(ret_ann) == 1
    mutations = op.find_mutations(ret_ann[0].node, AnnotationContext.RETURN, Registry())
    assert len(mutations) == 1
    assert mutations[0].mutated == "str | None"


def test_remove_optional_non_union() -> None:
    assert_mutations("x: int\n", RemoveOptional, expected=[])


def test_remove_optional_non_expr_basenode() -> None:
    # list[int] is a power/atom_expr node, not expr/arith_expr
    assert_mutations("x: list[int]\n", RemoveOptional, expected=[])


def test_remove_optional_all_none() -> None:
    assert_mutations("x: None | None\n", RemoveOptional, expected=[])


def test_add_optional_skips_self() -> None:
    source = "class Foo:\n    def bar(self) -> None:\n        pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    param_anns = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    op = AddOptional()
    for ann in param_anns:
        mutations = op.find_mutations(ann.node, AnnotationContext.PARAMETER, Registry())
        assert len(mutations) == 0


