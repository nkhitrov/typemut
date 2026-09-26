"""Tests for config parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from typemut.config import Config, load_config


def test_load_config_defaults():
    toml = '[typemut]\nmodule-path = "src/myproject"\ntest-command = "mypy src/"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = load_config(Path(f.name))

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
        cfg = load_config(Path(f.name))

    assert cfg.operators.remove_union_member is False
    assert cfg.operators.remove_literal_member is True


def test_load_config_plugins_default_empty():
    toml = '[typemut]\nmodule-path = "src"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = load_config(Path(f.name))

    assert cfg.plugins == []


def test_load_config_plugins():
    toml = '[typemut]\nmodule-path = "src"\nplugins = ["sqlalchemy"]\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml)
        f.flush()
        cfg = load_config(Path(f.name))

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
        cfg = load_config(Path(f.name))

    assert cfg.plugins == []
    assert "Ignoring invalid 'plugins' option" in caplog.text
    assert cfg.module_path == "src"


def load_toml(toml: str, tmp_path: Path) -> Config:
    path = tmp_path / "typemut.toml"
    path.write_text(toml)
    return load_config(path)


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
