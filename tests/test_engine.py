"""Tests for the engine: applying mutants, running them, recording results."""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from tests.fakes import RecordingProgressBar, StubExecutor, StubRunner, make_mutant
from typemut.db import Database, MutantRow
from typemut.engine import (
    MutationApplyError,
    MutationTester,
    RichProgressBar,
    SequentialExecutor,
    MutationApplier,
    OutcomeClassifier,
    ResultRecorder,
)
from typemut.runner import CommandResult, Outcome, ShellRunner

_PRINT_MTIME = f'{sys.executable} -c "import os; print(int(os.stat(\'test.py\').st_mtime))"'

_MULTILINE_ANNOTATION = "Callable[\n    [int],\n    str,\n]"
_MULTILINE_SOURCE = (
    "from typing import Callable\n"
    "\n"
    "\n"
    f"def f() -> {_MULTILINE_ANNOTATION}:\n"
    "    ...\n"
)


def _multiline_mutant(original: str) -> MutantRow:
    return make_mutant(line=4, col=11, original=original, mutated=f"{original} | None")


def _run(mutant: MutantRow, command: str, root: Path, timeout: int = 5) -> MutantRow:
    return MutationTester(ShellRunner(), command, timeout).run(mutant, root)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "test.py").write_text("x: int = 5\n")
    return tmp_path


class TestMutationTesterRun:
    def test_survived_when_command_passes(self, project: Path) -> None:
        result = _run(make_mutant(), "true", project)
        assert result.status == "survived"
        assert (project / "test.py").read_text() == "x: int = 5\n"

    def test_killed_when_command_fails(self, project: Path) -> None:
        result = _run(make_mutant(), "false", project)
        assert result.status == "killed"
        assert (project / "test.py").read_text() == "x: int = 5\n"

    def test_command_sees_mutated_file(self, project: Path) -> None:
        result = _run(make_mutant(), "cat test.py", project)
        assert result.output == "x: str = 5\n"

    def test_line_out_of_range(self, project: Path) -> None:
        result = _run(make_mutant(line=999, col=0), "true", project)
        assert (result.status, result.output) == ("error", "Line number out of range")

    def test_annotation_mismatch(self, project: Path) -> None:
        result = _run(make_mutant(original="float"), "true", project)
        assert result.status == "error"
        assert "Could not apply mutation" in (result.output or "")

    def test_multiline_annotation_applied(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text(_MULTILINE_SOURCE)

        result = _run(_multiline_mutant(_MULTILINE_ANNOTATION), "cat test.py && false", tmp_path)

        assert result.status == "killed"
        assert result.output == _MULTILINE_SOURCE.replace(
            _MULTILINE_ANNOTATION, f"{_MULTILINE_ANNOTATION} | None"
        )
        assert src.read_text() == _MULTILINE_SOURCE

    def test_multiline_annotation_mismatch(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text(_MULTILINE_SOURCE)

        result = _run(_multiline_mutant("Callable[\n    [int],\n    int,\n]"), "true", tmp_path)

        assert result.status == "error"
        assert "Could not apply mutation" in (result.output or "")
        assert src.read_text() == _MULTILINE_SOURCE

    def test_false_kill_detected(self, project: Path) -> None:
        command = "echo 'error: Name not defined  [name-defined]' >&2; exit 1"
        assert _run(make_mutant(), command, project).status == "error"

    def test_timeout_returns_killed(self, project: Path) -> None:
        result = _run(make_mutant(), "sleep 60", project, timeout=1)
        assert (result.status, result.output) == ("killed", "timeout")
        assert (project / "test.py").read_text() == "x: int = 5\n"

    def test_unwritable_file_is_error(self, project: Path) -> None:
        src = project / "test.py"
        src.chmod(0o444)
        result = _run(make_mutant(), "true", project)
        src.chmod(0o644)
        assert result.status == "error"
        assert "Failed to write mutation" in (result.output or "")
        assert src.read_text() == "x: int = 5\n"

    def test_command_runs_in_root(self, project: Path) -> None:
        runner = StubRunner(CommandResult(Outcome.PASSED, ""))
        MutationTester(runner, "mypy .", timeout=7).run(make_mutant(), project)
        assert runner.calls == [("mypy .", 7, project)]

    def test_original_mtime_restored(self, project: Path) -> None:
        src = project / "test.py"
        os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_123_456_789))

        _run(make_mutant(), "true", project)

        assert src.stat().st_mtime_ns == 1_700_000_000_123_456_789

    def test_mutants_get_content_derived_mtimes(self, project: Path) -> None:
        # mypy reuses its cache when size and whole-second mtime match, so
        # equal-size mutants must not share an mtime with each other or the original.
        os.utime(project / "test.py", ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

        str_mtime = _run(make_mutant(mutated="str"), _PRINT_MTIME, project).output
        set_mtime = _run(make_mutant(mutated="set"), _PRINT_MTIME, project).output
        str_mtime_again = _run(make_mutant(mutated="str"), _PRINT_MTIME, project).output

        assert len({str_mtime, set_mtime, "1700000000\n"}) == 3
        assert str_mtime == str_mtime_again


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(CommandResult(Outcome.PASSED, "ok"), ("survived", "ok"), id="passed"),
        pytest.param(
            CommandResult(Outcome.FAILED, "x  [arg-type]"), ("killed", "x  [arg-type]"), id="failed"
        ),
        pytest.param(
            CommandResult(Outcome.FAILED, "x  [syntax]"), ("error", "x  [syntax]"), id="false-kill"
        ),
        pytest.param(
            CommandResult(Outcome.PASSED, "x  [syntax]"), ("survived", "x  [syntax]"), id="note"
        ),
        pytest.param(CommandResult(Outcome.FAILED, ""), ("killed", ""), id="no-codes"),
        pytest.param(CommandResult(Outcome.TIMED_OUT, ""), ("killed", "timeout"), id="timeout"),
    ],
)
def test_classify(result: CommandResult, expected: tuple[str, str]) -> None:
    assert OutcomeClassifier().classify(result) == expected


class TestApplyMutation:
    def test_replaces_annotation(self) -> None:
        assert MutationApplier().apply("x: int = 5\n", make_mutant()) == "x: str = 5\n"

    def test_adds_required_import(self) -> None:
        mutant = make_mutant(line=1, mutated="Sequence[int]", original="int")
        assert MutationApplier().apply("x: int = 5\n", mutant) == (
            "from collections.abc import Sequence\nx: Sequence[int] = 5\n"
        )

    def test_mismatch_raises(self) -> None:
        with pytest.raises(MutationApplyError, match="expected 'int' at col 3, found 'str'"):
            MutationApplier().apply("x: str = 5\n", make_mutant())


class TestCheckBaseline:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(CommandResult(Outcome.PASSED, "clean"), (True, "clean"), id="passed"),
            pytest.param(CommandResult(Outcome.FAILED, "errors"), (False, "errors"), id="failed"),
            pytest.param(
                CommandResult(Outcome.TIMED_OUT, ""),
                (False, "Baseline check timed out"),
                id="timeout",
            ),
        ],
    )
    def test_result(self, result: CommandResult, expected: tuple[bool, str]) -> None:
        tester = MutationTester(StubRunner(result), "mypy .", timeout=5)
        assert tester.check_baseline(Path("root")) == expected

    def test_runs_in_root(self) -> None:
        runner = StubRunner(CommandResult(Outcome.PASSED, ""))
        MutationTester(runner, "mypy .", timeout=5).check_baseline(Path("root"))
        assert runner.calls == [("mypy .", 5, Path("root"))]


def test_sequential_executor_runs_every_mutant(project: Path) -> None:
    tester = MutationTester(StubRunner(CommandResult(Outcome.FAILED, "")), "mypy .", timeout=5)
    results = list(SequentialExecutor(tester, project).execute([make_mutant(1), make_mutant(2)]))
    assert [(r.id, r.status) for r in results] == [(1, "killed"), (2, "killed")]


class TestRunMutants:
    def test_stores_results_across_batches(self, tmp_db: Database) -> None:
        tmp_db.insert_many([make_mutant(None, line=line) for line in range(51)])
        progress = RecordingProgressBar()

        ResultRecorder(tmp_db, progress).record(tmp_db.get_pending(), StubExecutor("killed"))

        assert {m.status for m in tmp_db.get_all()} == {"killed"}
        assert progress.totals == [51]

    def test_stores_results_before_failure(self, tmp_db: Database) -> None:
        tmp_db.insert_many([make_mutant(None), make_mutant(None, "missing.py")])
        tester = MutationTester(StubRunner(CommandResult(Outcome.PASSED, "")), "true", timeout=5)
        root = Path(__file__).parent / "fixtures"
        (mutant, missing) = tmp_db.get_pending()
        executor = SequentialExecutor(tester, root)

        with pytest.raises(FileNotFoundError):
            ResultRecorder(tmp_db, RecordingProgressBar()).record([missing, mutant], executor)

        assert tmp_db.get_pending() == [mutant, missing]


def test_rich_progress_bar_yields_results() -> None:
    results = [make_mutant()]
    progress = RichProgressBar(Console(file=StringIO()))
    assert list(progress.track(results, total=1)) == results
