"""Tests for RemoveOptional and AddOptional operators."""

from __future__ import annotations

from pathlib import Path
import pytest

from typemut.discovery import AnnotationFinder
from typemut.model import AnnotationContext
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
    annotations = AnnotationFinder().find(Path("test.py"), source=source)

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
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    param_anns = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    op = AddOptional()
    for ann in param_anns:
        mutations = op.find_mutations(ann.node, AnnotationContext.PARAMETER, Registry())
        assert len(mutations) == 0


def test_add_optional_skips_typevar() -> None:
    source = 'from typing import TypeVar\nT = TypeVar("T")\n'
    annotations = AnnotationFinder().find(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    mutations = AddOptional().find_mutations(tvars[0].node, AnnotationContext.TYPEVAR, Registry())
    assert mutations == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from typing import TypeAlias\nX: TypeAlias = int\n", id="bare"),
        pytest.param("import typing\nX: typing.TypeAlias = int\n", id="dotted"),
    ],
)
def test_add_optional_skips_type_alias(source: str) -> None:
    assert_mutations(source, AddOptional, expected=[])


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("y: 'Baz'\n", ["'Baz | None'"], id="single-quoted"),
        pytest.param('y: "Baz"\n', ['"Baz | None"'], id="double-quoted"),
        pytest.param("y: 'list[Baz]'\n", ["'list[Baz] | None'"], id="quoted-generic"),
        pytest.param("y: 'Foo | None' = None\n", [], id="quoted-optional"),
        pytest.param("y: 'Any'\n", [], id="quoted-any"),
        pytest.param("y: ''\n", [], id="empty"),
        pytest.param('y: """Baz"""\n', [], id="triple-quoted"),
        pytest.param("y: r'Baz'\n", [], id="prefixed"),
        pytest.param("y: 'Baz' ''\n", [], id="concatenated"),
    ],
)
def test_add_optional_inside_forward_ref(source: str, expected: list[str]) -> None:
    # 'Baz' | None passes mypy but raises TypeError at runtime (str | None).
    assert_mutations(source, AddOptional, expected=expected)


def test_add_optional_forward_ref_replaces_whole_string() -> None:
    annotations = AnnotationFinder().find(Path("test.py"), source="y: 'Baz'\n")
    mutations = AddOptional().find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert [(m.line, m.col, m.original, m.mutated) for m in mutations] == [
        (1, 3, "'Baz'", "'Baz | None'"),
    ]


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param("x: ClassVar[int]\n", ["int | None"], id="classvar"),
        pytest.param("x: typing.ClassVar[int]\n", ["int | None"], id="typing-classvar"),
        pytest.param("x: t.ClassVar[int]\n", ["int | None"], id="aliased-module"),
        pytest.param("x: Final[int] = 1\n", ["int | None"], id="final"),
        pytest.param("x: Required[str]\n", ["str | None"], id="required"),
        pytest.param("x: NotRequired[str]\n", ["str | None"], id="not-required"),
        pytest.param("x: ReadOnly[str]\n", ["str | None"], id="read-only"),
        pytest.param("x: dataclasses.InitVar[int]\n", ["int | None"], id="init-var"),
        pytest.param(
            "x: ReadOnly[NotRequired[str]]\n", ["str | None"], id="nested-qualifiers"
        ),
        pytest.param("x: ClassVar['Foo']\n", ["'Foo | None'"], id="quoted-inside"),
        pytest.param("x: 'ClassVar[Foo]'\n", ["'ClassVar[Foo | None]'"], id="quoted-around"),
        pytest.param("x: ClassVar[int | None]\n", [], id="already-optional"),
        pytest.param("x: Final = 1\n", [], id="bare-final"),
        pytest.param("x: typing.ClassVar\n", [], id="bare-classvar"),
        pytest.param("x: Annotated[int, 1]\n", ["Annotated[int, 1] | None"], id="annotated"),
    ],
)
def test_add_optional_inside_type_qualifier(source: str, expected: list[str]) -> None:
    # ClassVar[int] | None is not a type: mypy reports valid-type and the
    # runtime raises TypeError. The optional value goes inside the qualifier.
    assert_mutations(source, AddOptional, expected=expected)


def test_add_optional_inside_qualifier_replaces_inner_type() -> None:
    annotations = AnnotationFinder().find(Path("test.py"), source="x: ClassVar[int]\n")
    mutations = AddOptional().find_mutations(
        annotations[0].node, AnnotationContext.VARIABLE, Registry()
    )
    assert [(m.line, m.col, m.original, m.mutated) for m in mutations] == [
        (1, 12, "int", "int | None"),
    ]
