"""Tests for plugin lookup and plugin-aware mutation discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.config import OperatorsConfig
from typemut.db import Database
from typemut.discovery import discover_annotations
from typemut.operators import get_enabled_operators
from typemut.plugins import find_mutations, get_plugins
from typemut.registry import Registry


def test_get_plugins_by_name() -> None:
    assert [plugin.name for plugin in get_plugins(["sqlalchemy"])] == ["sqlalchemy"]


def test_get_plugins_empty() -> None:
    assert get_plugins([]) == []


def test_get_plugins_unknown_name_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    plugins = get_plugins(["sqlalchemy", "django"])
    assert [plugin.name for plugin in plugins] == ["sqlalchemy"]
    assert "Skipping unknown plugin(s): django. Available plugins: fastapi, sqlalchemy" in caplog.text


def test_find_mutations_without_plugins_uses_core_operators() -> None:
    annotation = discover_annotations(Path("models.py"), source="id: Mapped[int]\n")[0]
    mutations = find_mutations(annotation, get_enabled_operators(OperatorsConfig()), Registry())
    assert {(m.operator, m.original, m.mutated) for m in mutations} == {
        ("AddOptional", "Mapped[int]", "Mapped[int] | None"),
    }


def write_project(root: Path, plugins: str) -> None:
    (root / "typemut.toml").write_text(
        f'[typemut]\nmodule-path = "src"\ntest-command = "true"\nplugins = {plugins}\n'
    )
    (root / "src").mkdir()
    (root / "src" / "models.py").write_text("id: Mapped[int]\n")


@pytest.mark.parametrize(
    "plugins,expected",
    [
        pytest.param("[]", {"Mapped[int] | None"}, id="disabled"),
        pytest.param('["sqlalchemy"]', {"int | None"}, id="enabled"),
    ],
)
def test_init_uses_configured_plugins(tmp_path: Path, plugins: str, expected: set[str]) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        write_project(Path(td), plugins)
        result = runner.invoke(main, ["init"])
        with Database(Path(td) / "typemut.sqlite") as db:
            mutated = {mutant.mutated_annotation for mutant in db.get_all()}
    assert result.exit_code == 0
    assert mutated == expected


def test_init_unknown_plugin_warns_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        write_project(Path(td), '["nope"]')
        result = runner.invoke(main, ["init"])
        with Database(Path(td) / "typemut.sqlite") as db:
            mutated = {mutant.mutated_annotation for mutant in db.get_all()}
    assert result.exit_code == 0
    assert mutated == {"Mapped[int] | None"}
    assert "Skipping unknown plugin(s): nope. Available plugins: fastapi, sqlalchemy" in caplog.text
