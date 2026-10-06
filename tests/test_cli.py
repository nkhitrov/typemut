"""Tests for CLI commands using click.testing.CliRunner."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.fakes import RecordingProgressBar, RecordingTerminateSignal, StubRunner
from typemut.app import App
from typemut.checkers import CheckerRegistry
from typemut.cli import main
from typemut.db import Database, MutantRow
from typemut.parallel import InlinePool
from typemut.runner import CommandResult, Outcome


def _app(outcome: Outcome = Outcome.FAILED, output: str = "") -> Callable[[Path], App]:
    """An app factory whose type checker always ends with *outcome*."""
    return partial(
        App, runner=StubRunner(CommandResult(outcome, output)), progress=RecordingProgressBar()
    )


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "typemut" in result.output


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "typemut, version" in result.output


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
        config.write_text('[typemut]\nmodule-path = "src"\ntest-command = "true"\n')
        src_dir = td_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x: int = 5\n")
        result = runner.invoke(main, ["init", "--config", "typemut.toml"])
    assert result.exit_code == 0
    assert "Found" in result.output


def _write_project(root: Path) -> None:
    """Project whose single mutant survives: the test command never fails."""
    (root / "typemut.toml").write_text('[typemut]\nmodule-path = "src"\ntest-command = "true"\n')
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
        db.insert_many(
            [
                MutantRow(
                    None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status="killed"
                ),
                MutantRow(
                    None, "a.py", "AddOptional", 2, 3, "int", "int | None", "", status="survived"
                ),
                MutantRow(
                    None, "a.py", "AddOptional", 3, 3, "int", "int | None", "", status="error"
                ),
            ]
        )
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
        db.insert_many(
            [
                MutantRow(
                    None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status="survived"
                ),
            ]
        )
    baseline = tmp_path / "b.json"
    runner = CliRunner()
    runner.invoke(
        main, ["report", "--db", str(db_path), "--baseline", str(baseline), "--update-baseline"]
    )
    result = runner.invoke(
        main, ["report", "--db", str(db_path), "--baseline", str(baseline), "--fail-under", "50"]
    )
    assert result.exit_code == 1
    assert "1 accepted, 0 new" in result.output
    assert "below --fail-under 50%" in result.output


def test_project_dir_option(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    runner = CliRunner()
    # isolated_filesystem restores the working directory that -C changes
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["-C", str(project), "init"])
    assert result.exit_code == 0
    assert (project / "typemut.sqlite").exists()


def test_init_missing_module_path(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        (Path(td) / "typemut.toml").write_text('[typemut]\nmodule-path = "nowhere"\n')
        result = runner.invoke(main, ["init"])
    assert result.exit_code == 1
    assert "Module path not found: nowhere" in result.output


def test_init_invalid_toml(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        (Path(td) / "typemut.toml").write_text("[typemut\n")
        result = runner.invoke(main, ["init"])
    assert result.exit_code == 1
    assert "Invalid TOML in typemut.toml" in result.output
    assert "Please fix the syntax and try again." in result.output


def test_exec_without_pending_mutants(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, ["exec"], obj=_app())
    assert result.exit_code == 0
    assert "No pending mutants" in result.output


def test_exec_runs_pending_mutants(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["init"], obj=_app())
        baseline_ok = runner.invoke(main, ["exec"], obj=_app(Outcome.PASSED))
        with Database(Path(td) / "typemut.sqlite") as db:
            statuses = {mutant.status for mutant in db.get_all()}
    assert baseline_ok.exit_code == 0
    assert "Done." in baseline_ok.output
    assert statuses == {"survived"}


def test_exec_baseline_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    make_app = _app(Outcome.FAILED, "app.py:1: error [misc]")
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["init"], obj=make_app)
        result = runner.invoke(main, ["exec"], obj=make_app)
    assert result.exit_code == 1
    assert "Baseline check failed" in result.output
    assert "app.py:1: error [misc]" in result.output


@pytest.mark.parametrize("command", ["exec", "run"])
def test_sigterm_interrupts_while_mutants_run(command: str, tmp_path: Path) -> None:
    runner = CliRunner()
    terminate_signal = RecordingTerminateSignal()
    make_app = partial(
        App,
        runner=StubRunner(CommandResult(Outcome.PASSED, "")),
        progress=RecordingProgressBar(),
        terminate_signal=terminate_signal,
    )
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, [command], obj=make_app)
    assert result.exit_code == 0
    assert (terminate_signal.entered, terminate_signal.exited) == (1, 1)


def test_run_nothing_to_test(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        (Path(td) / "src" / "app.py").write_text("x = 1\n")
        result = runner.invoke(main, ["run"], obj=_app())
    assert result.exit_code == 0
    assert "nothing to test" in result.output


def test_run_reports_progress(tmp_path: Path) -> None:
    runner = CliRunner()
    progress = RecordingProgressBar()
    make_app = partial(App, runner=StubRunner(CommandResult(Outcome.PASSED, "")), progress=progress)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, ["run"], obj=make_app)
    assert result.exit_code == 0
    assert progress.totals == [1]


def test_run_default_progress_bar(tmp_path: Path) -> None:
    runner = CliRunner()
    make_app = partial(App, runner=StubRunner(CommandResult(Outcome.PASSED, "")))
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(main, ["run"], obj=make_app)
    assert result.exit_code == 0
    assert "Running mutations..." in result.output


def _commit_project(root: Path) -> None:
    _write_project(root)
    for args in (
        ["init"],
        ["config", "user.email", "test@test.com"],
        ["config", "user.name", "Test"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def test_run_parallel_in_worktrees(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _commit_project(project)
    make_app = partial(App, worker_pool=InlinePool(), progress=RecordingProgressBar())
    db_path = str(tmp_path / "typemut.sqlite")

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main, ["-C", str(project), "run", "--jobs", "2", "--db", db_path], obj=make_app
        )

    assert result.exit_code == 0
    assert "Survived mutants" in result.output


def test_run_parallel_carries_checker_cache_into_worktrees(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(".mypy_cache/\n")
    _commit_project(project)
    (project / "typemut.toml").write_text(
        '[typemut]\nmodule-path = "src"\nchecker = "mypy"\n'
        'test-command = "test -f .mypy_cache/marker"\n'
    )
    subprocess.run(["git", "commit", "-am", "mypy"], cwd=project, capture_output=True, check=True)
    (project / ".mypy_cache").mkdir()
    (project / ".mypy_cache" / "marker").write_text("")
    make_app = partial(
        App,
        worker_pool=InlinePool(),
        progress=RecordingProgressBar(),
        checkers=CheckerRegistry.discover([], environ={}),
    )
    db_path = tmp_path / "typemut.sqlite"

    result = CliRunner().invoke(
        main, ["-C", str(project), "run", "--jobs", "2", "--db", str(db_path)], obj=make_app
    )

    assert result.exit_code == 0
    assert "Type checker: mypy (cache: .mypy_cache)" in result.output
    with Database(db_path) as db:
        assert {row.status for row in db.get_all()} == {"survived"}


def test_run_parallel_shares_absolute_checker_cache(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(".mypy_cache/\n")
    _commit_project(project)
    (project / "typemut.toml").write_text(
        '[typemut]\nmodule-path = "src"\nchecker = "mypy"\n'
        'test-command = "test -f .mypy_cache/marker"\n'
    )
    subprocess.run(["git", "commit", "-am", "mypy"], cwd=project, capture_output=True, check=True)
    (project / ".mypy_cache").mkdir()
    (project / ".mypy_cache" / "marker").write_text("")
    checkers = CheckerRegistry.discover([], environ={"MYPY_CACHE_DIR": str(project / ".mypy_cache")})
    make_app = partial(
        App, worker_pool=InlinePool(), progress=RecordingProgressBar(), checkers=checkers
    )
    db_path = tmp_path / "typemut.sqlite"

    result = CliRunner().invoke(
        main, ["-C", str(project), "run", "--jobs", "2", "--db", str(db_path)], obj=make_app
    )

    assert result.exit_code == 0
    with Database(db_path) as db:
        assert {row.status for row in db.get_all()} == {"killed"}


def test_run_parallel_warns_once_about_checker_cache_outside_project(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _commit_project(project)
    (project / "typemut.toml").write_text(
        '[typemut]\nmodule-path = "src"\nchecker = "mypy"\ntest-command = "true"\n'
    )
    subprocess.run(["git", "commit", "-am", "mypy"], cwd=project, capture_output=True, check=True)
    checkers = CheckerRegistry.discover([], environ={"MYPY_CACHE_DIR": "../outside"})
    make_app = partial(
        App, worker_pool=InlinePool(), progress=RecordingProgressBar(), checkers=checkers
    )
    db_path = tmp_path / "typemut.sqlite"

    result = CliRunner().invoke(
        main, ["-C", str(project), "run", "--jobs", "2", "--db", str(db_path)], obj=make_app
    )

    assert result.exit_code == 0
    assert caplog.text.count("is outside the project") == 1


def test_run_parallel_requires_git(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = runner.invoke(
            main, ["run", "--jobs", "2"], obj=partial(App, progress=RecordingProgressBar())
        )
    assert result.exit_code == 1
    assert "Failed to check git status" in result.output


def _html_db(path: Path) -> None:
    with Database(path) as db:
        db.insert_many(
            [
                MutantRow(
                    None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status="survived"
                ),
            ]
        )


def test_html_default_output(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _html_db(Path(td) / "typemut.sqlite")
        result = runner.invoke(main, ["html"], obj=_app())
        report = (Path(td) / "typemut-report.html").read_text()
    assert result.exit_code == 0
    assert "Report saved to typemut-report.html" in result.output
    assert "a.py" in report


def test_html_output_and_open(tmp_path: Path) -> None:
    opened: list[str] = []
    make_app = partial(App, open_browser=opened.append)
    db_path = tmp_path / "typemut.sqlite"
    out_path = tmp_path / "report.html"
    _html_db(db_path)

    result = CliRunner().invoke(
        main, ["html", "--db", str(db_path), "-o", str(out_path), "--open"], obj=make_app
    )

    assert result.exit_code == 0
    assert opened == [out_path.as_uri()]
    assert out_path.exists()


# Fails like pyright on an undefined name once ``x: int`` in src/app.py is mutated.
_PYRIGHT_LIKE_COMMAND = (
    "grep -q 'x: int$' src/app.py || "
    "{ echo '  /p/src/app.py:2:5 - error: \"Foo\" is not defined (reportUndefinedVariable)'; exit 1; }"
)


@pytest.mark.parametrize(
    ("checker_option", "checker", "status"),
    [
        pytest.param('checker = "pyright"\n', "pyright", "error", id="pyright"),
        pytest.param("", "generic", "killed", id="detected-generic"),
    ],
)
def test_run_classifies_output_with_checker(
    tmp_path: Path, checker_option: str, checker: str, status: str
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        (Path(td) / "typemut.toml").write_text(
            '[typemut]\nmodule-path = "src"\n'
            f"test-command = '''{_PYRIGHT_LIKE_COMMAND}'''\n{checker_option}"
        )
        result = runner.invoke(main, ["run"], obj=partial(App, progress=RecordingProgressBar()))
        with Database(Path(td) / "typemut.sqlite") as db:
            statuses = {mutant.status for mutant in db.get_all()}
    assert f"Type checker: {checker}" in result.output
    assert statuses == {status}


@pytest.mark.parametrize(
    ("test_command", "cache"),
    [
        pytest.param("mypy src", ".mypy_cache", id="default"),
        pytest.param("mypy --cache-dir build/mypy src", "build/mypy", id="relative-path"),
    ],
)
def test_run_describes_checker(test_command: str, cache: str, tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        (Path(td) / "typemut.toml").write_text(
            f'[typemut]\nmodule-path = "src"\ntest-command = "{test_command}"\n'
        )
        (Path(td) / "mypy.ini").write_text("[mypy]\n")
        app = partial(
            App,
            runner=StubRunner(CommandResult(Outcome.PASSED)),
            progress=RecordingProgressBar(),
            checkers=CheckerRegistry(environ={}),
        )
        result = runner.invoke(main, ["run"], obj=app)
    assert f"Type checker: mypy (config: mypy.ini; cache: {cache})" in result.output
