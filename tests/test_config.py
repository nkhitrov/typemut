"""Tests for config parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
    assert cfg.operators.swap_literal_value is True
