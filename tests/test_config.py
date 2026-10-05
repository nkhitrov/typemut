"""Tests for config parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from typemut.config import Config, ConfigLoader


def test_load_config_defaults():
    toml = '[typemut]\nmodule-path = "src/myproject"\ntest-command = "mypy src/"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = ConfigLoader().load(Path(f.name))

    assert cfg.module_path == "src/myproject"
    assert cfg.test_command == "mypy src/"
    assert cfg.timeout == 30
    assert cfg.operators.remove_union_member is True


def test_load_config_disable_operator():
    toml = """\
[typemut]
module-path = "src"
test-command = "mypy src/"

[typemut.operators]
remove-union-member = false
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = ConfigLoader().load(Path(f.name))

    assert cfg.operators.remove_union_member is False
    assert cfg.operators.remove_literal_member is True


def test_load_config_plugins_default_empty():
    toml = '[typemut]\nmodule-path = "src"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = ConfigLoader().load(Path(f.name))

    assert cfg.plugins == []


def test_load_config_plugins():
    toml = '[typemut]\nmodule-path = "src"\nplugins = ["sqlalchemy"]\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = ConfigLoader().load(Path(f.name))

    assert cfg.plugins == ["sqlalchemy"]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param('"sqlalchemy"', id="string-not-list"),
        pytest.param("[1, 2]", id="list-of-ints"),
    ],
)
def test_load_config_invalid_plugins_warns(value: str, caplog: pytest.LogCaptureFixture) -> None:
    toml = f'[typemut]\nmodule-path = "src"\nplugins = {value}\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = ConfigLoader().load(Path(f.name))

    assert cfg.plugins == []
    assert "Ignoring invalid 'plugins' option" in caplog.text
    assert cfg.module_path == "src"


def load_toml(toml: str, tmp_path: Path) -> Config:
    path = tmp_path / "typemut.toml"
    path.write_text(toml)
    return ConfigLoader().load(path)


def test_load_config_ignore_types(tmp_path: Path) -> None:
    cfg = load_toml(
        '[typemut]\nmodule-path = "src"\n\n'
        "[typemut.ignore-types]\n"
        'all = ["django.db.models.*"]\n'
        'add-optional = ["sqlalchemy.orm.Mapped"]\n',
        tmp_path,
    )
    assert cfg.ignore_types == {
        "all": ["django.db.models.*"],
        "add-optional": ["sqlalchemy.orm.Mapped"],
    }


def test_load_config_ignore_types_default_empty(tmp_path: Path) -> None:
    assert load_toml('[typemut]\nmodule-path = "src"\n', tmp_path).ignore_types == {}


@pytest.mark.parametrize(
    "toml_value,expected,message",
    [
        pytest.param(
            'ignore-types = ["sqlalchemy.orm.Mapped"]',
            {},
            "Ignoring invalid 'ignore-types' option",
            id="not-a-table",
        ),
        pytest.param(
            'ignore-types = { add-optionl = ["x.Y"], add-optional = ["x.Z"] }',
            {"add-optional": ["x.Z"]},
            "Ignoring unknown operator 'add-optionl' in 'ignore-types'",
            id="unknown-operator-key",
        ),
        pytest.param(
            'ignore-types = { add-optional = "x.Y", all = ["x.Z"] }',
            {"all": ["x.Z"]},
            "Ignoring invalid 'ignore-types.add-optional' option",
            id="value-not-a-list",
        ),
    ],
)
def test_load_config_invalid_ignore_types_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    toml_value: str,
    expected: dict[str, list[str]],
    message: str,
) -> None:
    cfg = load_toml(f'[typemut]\nmodule-path = "src"\n{toml_value}\n', tmp_path)
    assert cfg.ignore_types == expected
    assert message in caplog.text
    assert cfg.module_path == "src"


def test_load_config_checker(tmp_path: Path) -> None:
    cfg = load_toml(
        '[typemut]\nchecker = "pyright"\nchecker-version-command = "npx pyright --version"\n',
        tmp_path,
    )
    assert (cfg.checker, cfg.checker_version_command) == ("pyright", "npx pyright --version")


def test_load_config_checker_default_detects(tmp_path: Path) -> None:
    cfg = load_toml('[typemut]\nmodule-path = "src"\n', tmp_path)
    assert (cfg.checker, cfg.checker_version_command) == (None, None)


@pytest.mark.parametrize(
    ("toml_value", "message"),
    [
        pytest.param("checker = 1", "Ignoring invalid 'checker' option 1", id="checker"),
        pytest.param(
            'checker-version-command = ["mypy", "--version"]',
            "Ignoring invalid 'checker-version-command' option ['mypy', '--version']",
            id="version-command",
        ),
    ],
)
def test_load_config_invalid_checker_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, toml_value: str, message: str
) -> None:
    cfg = load_toml(f'[typemut]\nmodule-path = "src"\n{toml_value}\n', tmp_path)
    assert (cfg.checker, cfg.checker_version_command) == (None, None)
    assert message in caplog.text
    assert cfg.module_path == "src"


def test_load_config_incremental_defaults(tmp_path: Path) -> None:
    cfg = load_toml('[typemut]\nmodule-path = "src"\n', tmp_path)
    assert (cfg.incremental, cfg.max_duration, cfg.cache_key_files) == (
        False,
        None,
        ["uv.lock", "poetry.lock", "requirements*.txt"],
    )


def test_load_config_incremental(tmp_path: Path) -> None:
    cfg = load_toml(
        "[typemut]\nincremental = true\nmax-duration = 600\n"
        'cache-key-files = ["Pipfile.lock"]\n',
        tmp_path,
    )
    assert (cfg.incremental, cfg.max_duration, cfg.cache_key_files) == (
        True,
        600.0,
        ["Pipfile.lock"],
    )


def test_load_config_no_cache_key_files(tmp_path: Path) -> None:
    cfg = load_toml("[typemut]\ncache-key-files = []\n", tmp_path)
    assert cfg.cache_key_files == []


@pytest.mark.parametrize(
    ("toml_value", "message"),
    [
        pytest.param(
            'incremental = "yes"', "Ignoring invalid 'incremental' option 'yes'", id="incremental"
        ),
        pytest.param("max-duration = 0", "Ignoring invalid 'max-duration' option 0", id="zero"),
        pytest.param(
            "max-duration = true", "Ignoring invalid 'max-duration' option True", id="bool"
        ),
        pytest.param(
            'max-duration = "1h"', "Ignoring invalid 'max-duration' option '1h'", id="string"
        ),
        pytest.param(
            'cache-key-files = "uv.lock"',
            "Ignoring invalid 'cache-key-files' option 'uv.lock'",
            id="key-files",
        ),
    ],
)
def test_load_config_invalid_incremental_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, toml_value: str, message: str
) -> None:
    cfg = load_toml(f'[typemut]\nmodule-path = "src"\n{toml_value}\n', tmp_path)
    assert (cfg.incremental, cfg.max_duration, cfg.cache_key_files) == (
        False,
        None,
        ["uv.lock", "poetry.lock", "requirements*.txt"],
    )
    assert message in caplog.text
