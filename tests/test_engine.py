"""Tests for engine module — apply_mutation, check_baseline, run_single_mutant."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from typemut.db import Database, MutantRow
from typemut.engine import check_baseline, run_all_mutants, run_single_mutant


_PRINT_MTIME = (
    f'{sys.executable} -c "import os; print(int(os.stat(\'test.py\').st_mtime))"'
)


def _int_mutant(mutated: str) -> MutantRow:
    return MutantRow(
        id=1,
        module_path="test.py",
        operator="Test",
        line=1,
        col=3,
        original_annotation="int",
        mutated_annotation=mutated,
        description="test",
    )


class TestRunSingleMutant:
    def test_survived_when_command_passes(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant, "true", timeout=5, project_root=tmp_path
        )
        assert status == "survived"
        assert src.read_text() == "x: int = 5\n"

    def test_killed_when_command_fails(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant, "false", timeout=5, project_root=tmp_path
        )
        assert status == "killed"
        assert src.read_text() == "x: int = 5\n"

    def test_line_out_of_range(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=999,
            col=0,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant, "true", timeout=5, project_root=tmp_path
        )
        assert status == "error"

    def test_annotation_mismatch(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="float",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant, "true", timeout=5, project_root=tmp_path
        )
        assert status == "error"
        assert "Could not apply mutation" in (output or "")


    def test_false_kill_detected(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        # Use a command that fails and writes a false-kill error code to stderr
        status, output, duration = run_single_mutant(
            mutant,
            'python -c "import sys; sys.stderr.write(\'error: Name not defined [name-defined]\\n\'); sys.exit(1)"',
            timeout=5,
            project_root=tmp_path,
        )
        assert status == "error"

    def test_timeout_returns_killed(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant, "sleep 60", timeout=1, project_root=tmp_path
        )
        assert status == "killed"
        assert output == "timeout"
        # Ensure file is restored
        assert src.read_text() == "x: int = 5\n"

    def test_killed_with_stdout_output(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        mutant = MutantRow(
            id=1,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        status, output, duration = run_single_mutant(
            mutant,
            'python -c "import sys; sys.stdout.write(\'some output\\n\'); sys.exit(1)"',
            timeout=5,
            project_root=tmp_path,
        )
        assert status == "killed"
        assert "some output" in (output or "")

    def test_original_mtime_restored(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_123_456_789))

        run_single_mutant(_int_mutant("str"), "true", timeout=5, project_root=tmp_path)

        assert src.stat().st_mtime_ns == 1_700_000_000_123_456_789

    def test_mutants_get_content_derived_mtimes(self, tmp_path: Path) -> None:
        # mypy reuses its cache when size and whole-second mtime match, so
        # equal-size mutants must not share an mtime with each other or the original.
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")
        os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

        _, str_mtime, _ = run_single_mutant(
            _int_mutant("str"), _PRINT_MTIME, timeout=5, project_root=tmp_path
        )
        _, set_mtime, _ = run_single_mutant(
            _int_mutant("set"), _PRINT_MTIME, timeout=5, project_root=tmp_path
        )
        _, str_mtime_again, _ = run_single_mutant(
            _int_mutant("str"), _PRINT_MTIME, timeout=5, project_root=tmp_path
        )

        assert len({str_mtime, set_mtime, "1700000000\n"}) == 3
        assert str_mtime == str_mtime_again



class TestRunAllMutants:
    def test_run_all_mutants(self, tmp_path: Path) -> None:
        src = tmp_path / "test.py"
        src.write_text("x: int = 5\n")

        db = Database(tmp_path / "test.sqlite")
        mutant = MutantRow(
            id=None,
            module_path="test.py",
            operator="Test",
            line=1,
            col=3,
            original_annotation="int",
            mutated_annotation="str",
            description="test",
        )
        mid = db.insert_mutant(mutant)
        mutant.id = mid

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            run_all_mutants(db, [mutant], "true", timeout=5)
        finally:
            os.chdir(old_cwd)

        results = db.get_all()
        assert len(results) == 1
        assert results[0].status == "survived"
        db.close()


class TestCheckBaseline:
    def test_baseline_passes(self) -> None:
        ok, output = check_baseline("true", timeout=5)
        assert ok is True

    def test_baseline_fails(self) -> None:
        ok, output = check_baseline("false", timeout=5)
        assert ok is False

    def test_baseline_timeout(self) -> None:
        ok, output = check_baseline("sleep 60", timeout=1)
        assert ok is False
        assert "timed out" in output.lower()

    def test_baseline_stdout_fallback(self) -> None:
        ok, output = check_baseline(
            'python -c "import sys; sys.stdout.write(\'ok\\n\')"',
            timeout=5,
        )
        assert ok is True
        assert "ok" in output
