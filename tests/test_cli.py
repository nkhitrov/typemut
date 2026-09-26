"""Tests for CLI commands using click.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.db import Database, MutantRow


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


def _write_project(root: Path) -> None:
    """Project whose single mutant survives: the test command never fails."""
    (root / "typemut.toml").write_text(
        '[typemut]\nmodule-path = "src"\ntest-command = "true"\n'
    )
    src_dir = root / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("class A:\n    x: int\n")


@pytest.mark.parametrize(
    ("fail_under", "exit_code"),
    [
        ("100", 1),
        ("0", 0),
    ],
)
def test_run_fail_under(tmp_path: Path, fail_under: str, exit_code: int) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, ["run", "--fail-under", fail_under])
    assert result.exit_code == exit_code
    assert "Survived mutants" in result.output


def test_run_fail_under_message(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, ["run", "--fail-under", "100"])
    assert "Mutation score 0.0% is below --fail-under 100%" in result.output


@pytest.mark.parametrize(
    ("fail_under", "exit_code"),
    [
        ("50", 0),
        ("50.1", 1),
    ],
)
def test_report_fail_under(tmp_path: Path, fail_under: str, exit_code: int) -> None:
    db_path = tmp_path / "typemut.sqlite"
    with Database(db_path) as db:
        db.insert_many([
            MutantRow(None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status="killed"),
            MutantRow(None, "a.py", "AddOptional", 2, 3, "int", "int | None", "", status="survived"),
            MutantRow(None, "a.py", "AddOptional", 3, 3, "int", "int | None", "", status="error"),
        ])
    result = CliRunner().invoke(main, ["report", "--db", str(db_path), "--fail-under", fail_under])
    assert result.exit_code == exit_code


def test_report_fail_under_without_results(tmp_path: Path) -> None:
    db_path = str(tmp_path / "empty.sqlite")
    result = CliRunner().invoke(main, ["report", "--db", db_path, "--fail-under", "100"])
    assert result.exit_code == 0


def test_report_fail_under_out_of_range(tmp_path: Path) -> None:
    db_path = str(tmp_path / "empty.sqlite")
    result = CliRunner().invoke(main, ["report", "--db", db_path, "--fail-under", "101"])
    assert result.exit_code == 2


def test_run_baseline_accepts_known_survivors(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        update = runner.invoke(main, ["run", "--baseline", "b.json", "--update-baseline"])
        check = runner.invoke(main, ["run", "--baseline", "b.json"])
    assert update.exit_code == 0
    assert "Baseline b.json updated: 1 survived mutants" in update.output
    assert check.exit_code == 0
    assert "1 accepted, 0 new" in check.output


def test_run_baseline_fails_on_new_survivor(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["run", "--baseline", "b.json", "--update-baseline"])
        (Path(td) / "src" / "app.py").write_text("class A:\n    y: str\n")
        result = runner.invoke(main, ["run", "--baseline", "b.json"])
    assert result.exit_code == 1
    assert "0 accepted, 1 new" in result.output
    assert "1 baseline entries no longer survive" in result.output
    assert "new src/app.py:2  AddOptional  str → str | None" in result.output


def test_update_baseline_requires_baseline(tmp_path: Path) -> None:
    db_path = str(tmp_path / "empty.sqlite")
    result = CliRunner().invoke(main, ["report", "--db", db_path, "--update-baseline"])
    assert result.exit_code == 2
    assert "--update-baseline requires --baseline" in result.output


def test_report_baseline_with_fail_under(tmp_path: Path) -> None:
    db_path = tmp_path / "typemut.sqlite"
    with Database(db_path) as db:
        db.insert_many([
            MutantRow(None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status="survived"),
        ])
    baseline = tmp_path / "b.json"
    runner = CliRunner()
    runner.invoke(main, ["report", "--db", str(db_path), "--baseline", str(baseline), "--update-baseline"])
    result = runner.invoke(
        main, ["report", "--db", str(db_path), "--baseline", str(baseline), "--fail-under", "50"]
    )
    assert result.exit_code == 1
    assert "1 accepted, 0 new" in result.output
    assert "below --fail-under 50%" in result.output
