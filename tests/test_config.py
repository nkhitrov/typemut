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
    assert cfg.operators == {}


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

    assert cfg.operators == {"remove-union-member": False}


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


def test_load_config_keeps_unknown_operator_keys(tmp_path: Path) -> None:
    """Operator keys are checked by the app, which also knows plugin operators."""
    cfg = load_toml(
        '[typemut]\nmodule-path = "src"\n'
        'ignore-types = { my-op = ["x.Y"] }\n\n'
        "[typemut.operators]\nmy-op = false\n",
        tmp_path,
    )
    assert cfg.operators == {"my-op": False}
    assert cfg.ignore_types == {"my-op": ["x.Y"]}


@pytest.mark.parametrize(
    "toml,expected,message",
    [
        pytest.param(
            '[typemut]\noperators = ["add-optional"]\n',
            {},
            "Ignoring invalid 'operators' option",
            id="not-a-table",
        ),
        pytest.param(
            '[typemut.operators]\nadd-optional = "no"\nwiden-type = false\n',
            {"widen-type": False},
            "Ignoring invalid 'operators.add-optional' option 'no': expected true or false",
            id="value-not-a-bool",
        ),
    ],
)
def test_load_config_invalid_operators_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    toml: str,
    expected: dict[str, bool],
    message: str,
) -> None:
    assert load_toml(toml, tmp_path).operators == expected
    assert message in caplog.text
