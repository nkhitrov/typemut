"""Tests for plugin lookup and plugin-aware mutation discovery."""

from __future__ import annotations

from functools import partial
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.fakes import StubPlugin
from typemut.app import App
from typemut.cli import main
from typemut.config import OperatorsConfig
from typemut.db import Database
from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import (
    BUILTIN_PLUGINS,
    ENTRY_POINT_GROUP,
    PluginRegistry,
)
from typemut.registry import Registry


def test_get_plugins_by_name() -> None:
    assert [plugin.name for plugin in PluginRegistry().get(["sqlalchemy"])] == ["sqlalchemy"]


def test_get_plugins_empty() -> None:
    assert PluginRegistry().get([]) == []


def test_get_plugins_unknown_name_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    plugins = PluginRegistry().get(iter(["sqlalchemy", "django"]))
    assert [plugin.name for plugin in plugins] == ["sqlalchemy"]
    assert "Skipping unknown plugin(s): django. Available plugins: fastapi, sqlalchemy" in caplog.text


def _entry_point(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def test_discover_adds_entry_point_plugins() -> None:
    registry = PluginRegistry.discover([_entry_point("stub", "tests.fakes:StubPlugin")])
    plugins = registry.get(["fastapi", "sqlalchemy", "stub"])
    assert [plugin.name for plugin in plugins] == ["fastapi", "sqlalchemy", "stub"]
    assert type(plugins[2]) is StubPlugin


def test_discover_installed_entry_points() -> None:
    plugins = PluginRegistry.discover().get(BUILTIN_PLUGINS)
    assert [plugin.name for plugin in plugins] == list(BUILTIN_PLUGINS)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        pytest.param("tests.missing:Plugin", "Skipping plugin 'bad': failed to load", id="import"),
        pytest.param(
            "tests.fakes:make_mutant",
            "Skipping plugin 'bad': tests.fakes:make_mutant is not a typemut Plugin subclass",
            id="not-a-plugin",
        ),
        pytest.param(
            "tests.fakes:StubOperator",
            "Skipping plugin 'bad': tests.fakes:StubOperator is not a typemut Plugin subclass",
            id="other-class",
        ),
    ],
)
def test_discover_skips_broken_entry_points(
    value: str, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    registry = PluginRegistry.discover([_entry_point("bad", value)])
    assert registry.get(["bad"]) == []
    assert message in caplog.text


def test_find_mutations_without_plugins_uses_core_operators() -> None:
    annotation = AnnotationFinder().find(Path("models.py"), source="id: Mapped[int]\n")[0]
    mutations = MutationFinder(OperatorRegistry().enabled(OperatorsConfig()), Registry()).find(annotation)
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


def test_init_uses_injected_plugin_operators(tmp_path: Path) -> None:
    runner = CliRunner()
    make_app = partial(App, plugins=PluginRegistry({"stub": StubPlugin}))
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        write_project(Path(td), '["stub"]')
        result = runner.invoke(main, ["init"], obj=make_app)
    assert result.exit_code == 0
    assert "Enabled plugins: stub" in result.output
    assert "TypeVarVariance, Stub" in result.output
