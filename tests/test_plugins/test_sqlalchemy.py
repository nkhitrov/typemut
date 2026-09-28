"""Tests for the SQLAlchemy plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.db import MutantRow
from typemut.discovery import AnnotationFinder
from typemut.engine import MutationTester
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry
from typemut.runner import ShellRunner

REGISTRY = Registry(
    hierarchy={"BaseDB": ["UserDB"], "StrEnum": ["StatusEnum"]},
    class_to_base={"UserDB": "BaseDB", "StatusEnum": "StrEnum"},
)


def plugin_mutations(source: str) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *source* with the SQLAlchemy plugin enabled."""
    operators = OperatorRegistry().enabled()
    plugins = PluginRegistry().get(["sqlalchemy"])
    return {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(Path("models.py"), source=source)
        for mutation in MutationFinder(operators, REGISTRY, plugins).find(annotation)
    }


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            "id: Mapped[int] = mapped_column(primary_key=True)\n",
            {("AddOptional", "int", "int | None")},
            id="add-optional-inside-mapped",
        ),
        pytest.param(
            "email: Mapped[str | None]\n",
            {("RemoveOptional", "str | None", "str")},
            id="remove-optional-inside-mapped",
        ),
        pytest.param(
            "code: Mapped[int | str | None] = mapped_column()\n",
            {
                ("RemoveOptional", "int | str | None", "int | str"),
                ("RemoveUnionMember", "int | str | None", "str | None"),
                ("RemoveUnionMember", "int | str | None", "int | None"),
            },
            id="union-inside-mapped",
        ),
        pytest.param(
            "id: orm.Mapped[int]\n",
            {("AddOptional", "int", "int | None")},
            id="qualified-mapped",
        ),
        pytest.param(
            "status: Mapped[StatusEnum] = mapped_column()\n",
            {
                ("AddOptional", "StatusEnum", "StatusEnum | None"),
                ("WidenType", "StatusEnum", "StrEnum"),
            },
            id="column-keeps-widen-type",
        ),
        pytest.param(
            "payload: Mapped[dict[str, list[int]]] = mapped_column(JSONB)\n",
            {
                ("AddOptional", "dict[str, list[int]]", "dict[str, list[int]] | None"),
                ("WidenContainerType", "list[int]", "Sequence[int]"),
            },
            id="column-type-not-widened-nested-is",
        ),
    ],
)
def test_columns(source: str, expected: set[tuple[str, str, str]]) -> None:
    assert plugin_mutations(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            "user: Mapped[UserDB] = relationship(lazy='joined')\n",
            {("AddOptional", "UserDB", "UserDB | None")},
            id="many-to-one-no-widen-type",
        ),
        pytest.param(
            "user: Mapped[UserDB | None] = orm.relationship()\n",
            {("RemoveOptional", "UserDB | None", "UserDB")},
            id="nullable-many-to-one",
        ),
        pytest.param(
            'roles: Mapped[list["RoleDB"]] = relationship(lazy="noload")\n',
            set(),
            id="collection-not-widened-nor-optional",
        ),
        pytest.param(
            "users: Mapped[set[UserDB]] = relationship()\n",
            set(),
            id="set-collection",
        ),
        pytest.param(
            "users: WriteOnlyMapped[UserDB] = relationship()\n",
            set(),
            id="write-only",
        ),
        pytest.param(
            "users: DynamicMapped[UserDB] = relationship()\n",
            set(),
            id="dynamic",
        ),
    ],
)
def test_relationships(source: str, expected: set[tuple[str, str, str]]) -> None:
    assert plugin_mutations(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            'user: Mapped["UserDB"] = relationship()\n',
            {("AddOptional", '"UserDB"', '"UserDB | None"')},
            id="forward-ref-add-optional",
        ),
        pytest.param(
            "profile: Mapped['ProfileDB | None'] = relationship()\n",
            {("RemoveOptional", "'ProfileDB | None'", "'ProfileDB'")},
            id="forward-ref-remove-optional",
        ),
        pytest.param(
            'user: Mapped["UserDB"] = mapped_column()\n',
            {
                ("AddOptional", '"UserDB"', '"UserDB | None"'),
                ("WidenType", '"UserDB"', '"BaseDB"'),
            },
            id="forward-ref-column",
        ),
        pytest.param(
            'user: Mapped["""UserDB"""] = relationship()\n',
            set(),
            id="forward-ref-triple-quoted",
        ),
        pytest.param(
            'user: Mapped[b"UserDB"] = relationship()\n',
            set(),
            id="forward-ref-bytes",
        ),
        pytest.param(
            'user: Mapped["UserDB"\n    ""] = relationship()\n',
            set(),
            id="forward-ref-concatenated",
        ),
        pytest.param(
            'user: Mapped[""] = relationship()\n',
            set(),
            id="forward-ref-empty",
        ),
    ],
)
def test_forward_refs(source: str, expected: set[tuple[str, str, str]]) -> None:
    assert plugin_mutations(source) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            "x: int\n",
            {("AddOptional", "int", "int | None")},
            id="plain-annotation",
        ),
        pytest.param(
            "def f(x: Mapped[int]) -> list[int]: ...\n",
            {
                ("AddOptional", "list[int]", "list[int] | None"),
                ("WidenContainerType", "list[int]", "Sequence[int]"),
            },
            id="non-mapped-keeps-core-rules",
        ),
        pytest.param(
            "x: Mapped[int, str]\n",
            set(),
            id="mapped-with-several-arguments",
        ),
        pytest.param(
            "x: Other[int]\n",
            {("AddOptional", "Other[int]", "Other[int] | None")},
            id="other-generic",
        ),
        pytest.param(
            "x: factory()[int]\n",
            {("AddOptional", "factory()[int]", "factory()[int] | None")},
            id="subscripted-call",
        ),
        pytest.param(
            'from typing import TypeVar\nT = TypeVar("T", bound=Mapped[int])\n',
            {
                (
                    "TypeVarVariance",
                    'TypeVar("T", bound=Mapped[int])',
                    'TypeVar("T", bound=Mapped[int], covariant=True)',
                ),
                (
                    "TypeVarVariance",
                    'TypeVar("T", bound=Mapped[int])',
                    'TypeVar("T", bound=Mapped[int], contravariant=True)',
                ),
            },
            id="typevar-left-to-core",
        ),
    ],
)
def test_annotations_left_to_core(source: str, expected: set[tuple[str, str, str]]) -> None:
    assert plugin_mutations(source) == expected


def test_returned_mapped_is_unwrapped() -> None:
    source = "@declared_attr\ndef user_id(cls) -> Mapped[int]:\n    ...\n"
    assert plugin_mutations(source) == {("AddOptional", "int", "int | None")}


def test_plugin_has_no_extra_operators() -> None:
    assert PluginRegistry().get(["sqlalchemy"])[0].operators() == []


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param(
            "class A:\n    id: Mapped[int] = mapped_column()\n",
            "class A:\n    id: Mapped[int | None] = mapped_column()\n",
            id="column",
        ),
        pytest.param(
            'class A:\n    user: Mapped["UserDB"] = relationship()\n',
            'class A:\n    user: Mapped["UserDB | None"] = relationship()\n',
            id="forward-ref",
        ),
    ],
)
def test_mutation_applies_inside_mapped(tmp_path: Path, source: str, expected: str) -> None:
    (tmp_path / "models.py").write_text(source)
    annotation = AnnotationFinder().find(Path("models.py"), source=source)[0]
    mutation = MutationFinder(OperatorRegistry().enabled(), Registry(), PluginRegistry().get(["sqlalchemy"])).find(annotation)[0]
    mutant = MutantRow(
        id=1,
        module_path="models.py",
        operator=mutation.operator,
        line=mutation.line,
        col=mutation.col,
        original_annotation=mutation.original,
        mutated_annotation=mutation.mutated,
        description=mutation.description,
    )

    result = MutationTester(ShellRunner(), "cp models.py mutated.py", timeout=5).run(
        mutant, tmp_path
    )

    assert result.status == "survived"
    assert (tmp_path / "mutated.py").read_text() == expected
    assert (tmp_path / "models.py").read_text() == source
