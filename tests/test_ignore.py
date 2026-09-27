"""Tests for per-operator ignored types ([typemut.ignore-types])."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.config import OperatorsConfig
from typemut.db import Database
from typemut.discovery import discover_annotations
from typemut.ignore import IgnoredTypes
from typemut.imports import package_of
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry, find_mutations
from typemut.registry import Registry

REGISTRY = Registry(
    hierarchy={"Animal": ["Cat"], "DeclarativeBase": ["UserDB"]},
    class_to_base={"Cat": "Animal", "UserDB": "DeclarativeBase"},
    base_import_lines={"DeclarativeBase": "from sqlalchemy.orm import DeclarativeBase"},
)

MAPPED = "sqlalchemy.orm.Mapped"


def mutated(
    source: str,
    ignore: dict[str, list[str]],
    file: Path = Path("models.py"),
    plugins: list[str] | None = None,
) -> set[str]:
    """Mutated annotations of every annotation in *source* with the given ignore rules."""
    operators = OperatorRegistry().enabled(OperatorsConfig())
    ignored = IgnoredTypes(ignore)
    return {
        mutation.mutated
        for annotation in discover_annotations(file, source=source)
        for mutation in find_mutations(
            annotation, operators, REGISTRY, PluginRegistry().get(plugins or []), ignored
        )
    }


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from sqlalchemy.orm import Mapped\nx: Mapped[int]\n", id="from-import"),
        pytest.param("from sqlalchemy.orm import Mapped as M\nx: M[int]\n", id="alias"),
        pytest.param("import sqlalchemy.orm as orm\nx: orm.Mapped[int]\n", id="module-alias"),
        pytest.param("import sqlalchemy.orm\nx: sqlalchemy.orm.Mapped[int]\n", id="dotted"),
        pytest.param(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from sqlalchemy.orm import Mapped\n"
            "x: Mapped[int]\n",
            id="type-checking-import",
        ),
    ],
)
def test_ignored_type_is_resolved_through_imports(source: str) -> None:
    assert mutated(source, {"add-optional": [MAPPED]}) == set()


def test_without_ignore_rules_everything_is_mutated() -> None:
    source = "from sqlalchemy.orm import Mapped\nx: Mapped[int]\n"
    assert mutated(source, {}) == {"Mapped[int] | None"}


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("sqlalchemy.*", id="package-glob"),
        pytest.param("sqlalchemy.orm.Map*", id="name-glob"),
    ],
)
def test_glob_patterns(pattern: str) -> None:
    source = "from sqlalchemy.orm import Mapped\nx: Mapped[int]\n"
    assert mutated(source, {"add-optional": [pattern]}) == set()


@pytest.mark.parametrize(
    "ignore,expected",
    [
        pytest.param(
            {},
            {"Sequence[Mapped[int]]", "list[Mapped[int]] | None"},
            id="nothing-ignored",
        ),
        pytest.param(
            {"widen-container-type": [MAPPED]},
            {"list[Mapped[int]] | None"},
            id="only-widen-container-ignores",
        ),
        pytest.param(
            {"widen-container-type": [MAPPED], "add-optional": [MAPPED]},
            set(),
            id="both-ignore",
        ),
        pytest.param({"all": [MAPPED]}, set(), id="all-operators"),
    ],
)
def test_ignore_is_per_operator(ignore: dict[str, list[str]], expected: set[str]) -> None:
    source = "from sqlalchemy.orm import Mapped\nx: list[Mapped[int]]\n"
    assert mutated(source, ignore) == expected


@pytest.mark.parametrize(
    "ignore,expected",
    [
        # WidenType replaces just the class name: Cat -> Animal inside Mapped[...]
        pytest.param({"add-optional": [MAPPED]}, {"Animal"}, id="widen-type-still-runs"),
        pytest.param({"widen-type": [MAPPED]}, {"Mapped[Cat] | None"}, id="add-optional-runs"),
        pytest.param(
            {"all": [MAPPED], "widen-type": ["nothing.*"]},
            set(),
            id="all-adds-to-operator-list",
        ),
    ],
)
def test_other_operators_keep_mutating(ignore: dict[str, list[str]], expected: set[str]) -> None:
    source = "from sqlalchemy.orm import Mapped\nx: Mapped[Cat]\n"
    assert mutated(source, ignore) == expected


def test_annotations_without_ignored_types_are_mutated() -> None:
    source = "from sqlalchemy.orm import Mapped\nx: int\n"
    assert mutated(source, {"all": [MAPPED]}) == {"int | None"}


def test_unresolved_name_is_never_ignored() -> None:
    # Mapped is not imported here, so it can't be sqlalchemy's Mapped
    assert mutated("x: Mapped[int]\n", {"all": [MAPPED]}) == {"Mapped[int] | None"}


@pytest.mark.parametrize(
    "source,ignore,expected",
    [
        pytest.param(
            "x: UserDB\n",
            {"widen-type": ["sqlalchemy.orm.DeclarativeBase"]},
            {"UserDB | None"},
            id="widen-to-ignored-base",
        ),
        pytest.param(
            "x: UserDB\n",
            {},
            {"UserDB | None", "DeclarativeBase"},
            id="widen-to-base-without-ignore",
        ),
        pytest.param(
            "x: list[int]\n",
            {"widen-container-type": ["collections.abc.*"]},
            {"list[int] | None"},
            id="widen-to-ignored-stdlib-abc",
        ),
    ],
)
def test_mutations_introducing_ignored_types_are_dropped(
    source: str, ignore: dict[str, list[str]], expected: set[str]
) -> None:
    assert mutated(source, ignore) == expected


def test_relative_import_resolves_to_project_package(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    source = "from .types import Box\nx: Box[int]\n"
    assert mutated(source, {"add-optional": ["app.types.*"]}, file=package / "models.py") == set()


def test_package_of_nested_package(tmp_path: Path) -> None:
    (tmp_path / "app" / "sub").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "sub" / "__init__.py").write_text("")
    assert package_of(tmp_path / "app" / "sub" / "module.py") == "app.sub"


def test_package_of_outside_package(tmp_path: Path) -> None:
    assert package_of(tmp_path / "module.py") == ""


def test_plugin_still_mutates_ignored_types() -> None:
    source = "from sqlalchemy.orm import Mapped\nx: Mapped[int]\n"
    assert mutated(source, {"all": [MAPPED]}, plugins=["sqlalchemy"]) == {"int | None"}


def test_init_applies_ignore_types(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        root = Path(td)
        (root / "typemut.toml").write_text(
            '[typemut]\nmodule-path = "src"\ntest-command = "true"\n\n'
            '[typemut.ignore-types]\nadd-optional = ["sqlalchemy.orm.Mapped"]\n'
        )
        (root / "src").mkdir()
        (root / "src" / "models.py").write_text(
            "from sqlalchemy.orm import Mapped\nid: Mapped[int]\nname: str\n"
        )
        result = runner.invoke(main, ["init"])
        with Database(root / "typemut.sqlite") as db:
            mutants = {mutant.mutated_annotation for mutant in db.get_all()}
    assert result.exit_code == 0
    assert mutants == {"str | None"}
