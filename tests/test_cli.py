"""Tests for CLI commands using click.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from typemut.cli import main


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "typemut" in result.output


def test_init_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output


def test_report_missing_db(tmp_path: Path) -> None:
    runner = CliRunner()
    db_path = str(tmp_path / "nonexistent.sqlite")
    result = runner.invoke(main, ["report", "--db", db_path])
    assert result.exit_code == 0
    assert "No results" in result.output


def test_init_missing_config(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["init", "--config", "nonexistent.toml"])
    assert result.exit_code != 0


def test_init_with_minimal_project(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        td_path = Path(td)
        config = td_path / "typemut.toml"
        config.write_text(
            '[typemut]\nmodule-path = "src"\ntest-command = "true"\n'
        )
        src_dir = td_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x: int = 5\n")
        result = runner.invoke(main, ["init", "--config", "typemut.toml"])
    assert result.exit_code == 0
    assert "Found" in result.output
