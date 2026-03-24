"""Tests for engine module — apply_mutation, check_baseline, run_single_mutant."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from typemut.db import MutantRow
from typemut.engine import check_baseline, run_single_mutant


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
