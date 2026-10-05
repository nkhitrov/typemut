"""End-to-end tests of incremental runs: kills reused across ``typemut run --incremental``."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from tests.fakes import RecordingProgressBar, StepClock
from typemut.app import App
from typemut.checkers import CheckerRegistry
from typemut.cli import main
from typemut.db import Database

# Fails like mypy, with an error in src/use.py, once ``x: int`` in src/app.py
# is mutated; mutants of ``y: str`` survive.
_TEST_COMMAND = (
    "grep -q '^    x: int$' src/app.py || "
    "{ echo 'src/use.py:2: error: Argument 1 has incompatible type  [arg-type]'; exit 1; }"
)
_CONFIG = (
    '[typemut]\nmodule-path = "src"\n'
    f"test-command = '''{_TEST_COMMAND}'''\n"
    'checker = "mypy"\n'
    'checker-version-command = "echo mypy VERSION"\n'
)


def _write_project(root: Path, version: str = "1.0.0") -> None:
    """``app.py`` has the annotations; the error file ``use.py`` imports it and ``c.py``."""
    (root / "typemut.toml").write_text(_CONFIG.replace("VERSION", version))
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text("class A:\n    x: int\n    y: str\n")
    (src / "use.py").write_text("import c\nimport app\n")
    (src / "c.py").write_text("z = 1\n")
    (src / "other.py").write_text("w = 1\n")


def _app(
    typemut_version: str = "1", clock: Callable[[], float] = time.monotonic
) -> Callable[[Path], App]:
    return partial(
        App,
        progress=RecordingProgressBar(),
        checkers=CheckerRegistry(environ={}),
        typemut_version=typemut_version,
        clock=clock,
    )


def _run(runner: CliRunner, *args: str, app: Callable[[Path], App] | None = None) -> Result:
    return runner.invoke(main, ["run", *args], obj=app or _app())


def _statuses(root: Path) -> Sequence[str]:
    with Database(root / "typemut.sqlite") as db:
        return sorted(mutant.status for mutant in db.get_all())


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_first_run_has_no_earlier_results(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        result = _run(runner, "--incremental")
    assert result.exit_code == 0
    assert "Result cache reset: no earlier results." in result.output
    assert "Reused 0 cached kills." in result.output
    assert "Rerunning" not in result.output


def test_later_runs_only_run_kills_not_reused(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        first = _run(runner, "--incremental")
        statuses = _statuses(Path(td))
        second = _run(runner, "--incremental")
        third = _run(runner, "--incremental")
        reused_statuses = _statuses(Path(td))
    kills = statuses.count("killed")
    survivors = len(statuses) - kills
    assert kills > 0
    assert survivors > 0
    assert f"Running {len(statuses)} mutations" in first.output
    assert f"Reused {kills} cached kills." in second.output
    assert f"Running {survivors} mutations" in second.output
    assert f"Reused {kills} cached kills." in third.output
    assert "Result cache reset" not in third.output
    assert reused_statuses == statuses


def test_without_incremental_nothing_is_reused(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        result = _run(runner)
        statuses = _statuses(Path(td))
    assert "Reused" not in result.output
    assert f"Running {len(statuses)} mutations" in result.output


def test_run_without_incremental_keeps_cached_kills(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        kills = _statuses(Path(td)).count("killed")
        _run(runner)
        result = _run(runner, "--incremental")
    assert f"Reused {kills} cached kills." in result.output
    assert "Rerunning" not in result.output


def test_cache_reset_drops_kills_recorded_before(tmp_path: Path, runner: CliRunner) -> None:
    """A kill with the old checker version, still in the mutants table, is not reused."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["init"], obj=_app())
        runner.invoke(
            main,
            ["exec", "--incremental", "--max-duration", "1.5"],
            obj=_app(clock=StepClock()),
        )
        first = _statuses(Path(td))
        (Path(td) / "typemut.toml").write_text(_CONFIG.replace("VERSION", "1.1.0"))
        resumed = runner.invoke(main, ["exec", "--incremental"], obj=_app())
        kills = _statuses(Path(td)).count("killed")
        runner.invoke(main, ["init"], obj=_app())
        result = runner.invoke(main, ["exec", "--incremental"], obj=_app())
    assert first.count("killed") == 1
    assert "Result cache reset: checker version changed." in resumed.output
    assert "Result cache reset" not in result.output
    assert f"Reused {kills - 1} cached kills." in result.output


def test_incremental_option_in_config(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        config = Path(td) / "typemut.toml"
        config.write_text(config.read_text() + "incremental = true\n")
        _run(runner)
        enabled = _run(runner)
        disabled = _run(runner, "--no-incremental")
    assert "Reused" in enabled.output
    assert "Reused" not in disabled.output


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("src/app.py", "Rerunning {kills} kills whose files changed", id="mutated-file"),
        pytest.param("src/use.py", "Rerunning {kills} kills whose files changed", id="error-file"),
        pytest.param(
            "src/c.py", "Rerunning {kills} kills whose files changed", id="imported-by-error-file"
        ),
        pytest.param(
            "src/other.py", "Reused {kills} cached kills.", id="unrelated-file"
        ),
    ],
)
def test_changed_file_invalidates_kills(
    path: str, expected: str, tmp_path: Path, runner: CliRunner
) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        kills = _statuses(Path(td)).count("killed")
        changed = Path(td) / path
        changed.write_text(changed.read_text() + "# changed\n")
        result = _run(runner, "--incremental")
    assert expected.format(kills=kills) in result.output


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param("mypy.ini", "checker config mypy.ini changed", id="checker-config"),
        pytest.param("uv.lock", "file uv.lock changed", id="lockfile"),
    ],
)
def test_changed_input_file_resets_cache(
    change: str, reason: str, tmp_path: Path, runner: CliRunner
) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        (Path(td) / change).write_text("before\n")
        _write_project(Path(td))
        _run(runner, "--incremental")
        (Path(td) / change).write_text("after\n")
        result = _run(runner, "--incremental")
    assert f"Result cache reset: {reason}." in result.output
    assert "Reused 0 cached kills." in result.output


def test_new_typemut_version_resets_cache(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental", app=_app("1"))
        result = _run(runner, "--incremental", app=_app("2"))
    assert "Result cache reset: typemut version changed." in result.output


def test_new_checker_version_resets_cache(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        (Path(td) / "typemut.toml").write_text(_CONFIG.replace("VERSION", "1.1.0"))
        result = _run(runner, "--incremental")
    assert "Result cache reset: checker version changed." in result.output


def test_unknown_checker_version_leaves_the_cache_alone(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        config = Path(td) / "typemut.toml"
        _run(runner, "--incremental")
        kills = _statuses(Path(td)).count("killed")
        config.write_text(_CONFIG.replace("echo mypy VERSION", "false"))
        unknown = _run(runner, "--incremental")
        config.write_text(_CONFIG.replace("VERSION", "1.0.0"))
        known = _run(runner, "--incremental")
    assert "mypy version unknown: result cache not used" in unknown.output
    assert "Reused" not in unknown.output
    assert "Result cache reset" not in unknown.output
    assert "Result cache reset" not in known.output
    assert f"Reused {kills} cached kills." in known.output


def test_generic_checker_never_uses_the_cache(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        config = Path(td) / "typemut.toml"
        config.write_text(config.read_text().replace('checker = "mypy"', 'checker = "generic"'))
        _run(runner, "--incremental")
        result = _run(runner, "--incremental")
        with Database(Path(td) / "typemut.sqlite") as db:
            cached = db.cache.load()
    assert "generic checker: kills are never reused" in result.output
    assert "version unknown" not in result.output
    assert "Reused" not in result.output
    assert len(cached) == 0


def test_refresh_stores_results_in_the_cache(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner)
        statuses = _statuses(Path(td))
        runner.invoke(main, ["init"], obj=_app())
        refreshed = runner.invoke(main, ["exec", "--refresh"], obj=_app())
        with Database(Path(td) / "typemut.sqlite") as db:
            cached = sorted(row.status for row in db.cache.load().values())
        after = _run(runner, "--incremental")
    assert "Refreshing the result cache: every pending mutant runs." in refreshed.output
    assert f"Running {len(statuses)} mutations" in refreshed.output
    assert cached == statuses
    assert f"Reused {statuses.count('killed')} cached kills." in after.output


def test_new_stub_invalidates_kills(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        kills = _statuses(Path(td)).count("killed")
        (Path(td) / "src" / "app.pyi").write_text("class A:\n    x: object\n")
        result = _run(runner, "--incremental")
    assert f"Rerunning {kills} kills whose files changed" in result.output


def test_results_kept_when_the_cache_missed_them(tmp_path: Path, runner: CliRunner) -> None:
    """A run killed before it stored its results in the cache still has them in its mutants."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental")
        with Database(Path(td) / "typemut.sqlite") as db:
            killed = [mutant for mutant in db.get_all() if mutant.status == "killed"]
            db.cache.upsert(replace(mutant, status="survived", depends=None) for mutant in killed)
        kills = len(killed)
        result = _run(runner, "--incremental")
    assert f"Reused {kills} cached kills" in result.output


def test_max_duration_stops_and_fails_the_gate(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        stopped = _run(
            runner, "--incremental", "--max-duration", "1.5", app=_app(clock=StepClock())
        )
        statuses = _statuses(Path(td))
        resumed = _run(runner, "--incremental")
    not_run = statuses.count("pending")
    assert not_run == len(statuses) - 1
    assert stopped.exit_code == 1
    assert f"Stopped after max-duration: {not_run} mutants not run." in stopped.output
    assert f"{not_run} mutants not run yet (stopped early or interrupted)" in stopped.output
    assert resumed.exit_code == 0
    assert f"Running {len(statuses) - statuses.count('killed')} mutations" in resumed.output


def test_max_duration_from_config(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        config = Path(td) / "typemut.toml"
        config.write_text(config.read_text() + "max-duration = 0.5\n")
        result = _run(runner, app=_app(clock=StepClock()))
        statuses = _statuses(Path(td))
    assert result.exit_code == 1
    assert set(statuses) == {"pending"}


def test_exec_incremental(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["init"], obj=_app())
        runner.invoke(main, ["exec", "--incremental"], obj=_app())
        runner.invoke(main, ["init"], obj=_app())
        result = runner.invoke(main, ["exec", "--incremental"], obj=_app())
    assert result.exit_code == 0
    assert "Reused" in result.output
    assert "Reused 0 cached kills" not in result.output


def test_reuse_keeps_the_baseline_gate(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        _run(runner, "--incremental", "--baseline", "b.json", "--update-baseline")
        survivors = _statuses(Path(td)).count("survived")
        check = _run(runner, "--incremental", "--baseline", "b.json")
    assert "Reused" in check.output
    assert check.exit_code == 0
    assert f"{survivors} accepted, 0 new" in check.output


def test_report_fails_gate_with_pending_mutants(tmp_path: Path, runner: CliRunner) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _write_project(Path(td))
        runner.invoke(main, ["init"], obj=_app())
        result = runner.invoke(main, ["report", "--baseline", "b.json", "--update-baseline"])
        written = (Path(td) / "b.json").exists()
    assert result.exit_code == 1
    assert "mutants not run yet (stopped early or interrupted); run exec again" in result.output
    assert not written
