"""Tests for config parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from typemut.config import load_config


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
