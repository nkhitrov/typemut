"""Mutation execution loop."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from rich.progress import Progress

from typemut.db import Database, MutantRow


def run_single_mutant(
    mutant: MutantRow,
    test_command: str,
    timeout: int,
) -> tuple[str, str | None, float]:
    """Run a single mutation, return (status, output, duration)."""
    file_path = Path(mutant.module_path)
    original_source = file_path.read_text()

    # Find and replace the annotation at the correct position
    lines = original_source.splitlines(keepends=True)
    line_idx = mutant.line - 1

    if line_idx >= len(lines):
        return "error", "Line number out of range", 0.0

    line = lines[line_idx]
    # Replace at exact column position
    col = mutant.col
    orig = mutant.original_annotation
    end_col = col + len(orig)
    if line[col:end_col] != orig:
        return "error", f"Could not apply mutation — expected '{orig}' at col {col}, found '{line[col:end_col]}'", 0.0
    new_line = line[:col] + mutant.mutated_annotation + line[end_col:]

    lines[line_idx] = new_line
    mutated_source = "".join(lines)

    file_path.write_text(mutated_source)
    start = time.monotonic()

    try:
        result = subprocess.run(
            test_command,
            shell=True,
            timeout=timeout,
            capture_output=True,
        )
        duration = time.monotonic() - start
        # exit 0 = no type errors = mutant SURVIVED (bad)
        # exit != 0 = type errors = mutant KILLED (good)
        killed = result.returncode != 0
        status = "killed" if killed else "survived"
        output = result.stderr.decode(errors="replace")
        if not output:
            output = result.stdout.decode(errors="replace")
        return status, output, duration
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return "killed", "timeout", duration
    finally:
        file_path.write_text(original_source)


def check_baseline(test_command: str, timeout: int) -> tuple[bool, str]:
    """Run test command on unmodified code. Returns (ok, output)."""
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            timeout=timeout,
            capture_output=True,
        )
        output = result.stderr.decode(errors="replace")
        if not output:
            output = result.stdout.decode(errors="replace")
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Baseline check timed out"


def run_all_mutants(
    db: Database,
    mutants: list[MutantRow],
    test_command: str,
    timeout: int,
) -> None:
    """Run all pending mutants sequentially with progress bar."""
    with Progress() as progress:
        task = progress.add_task("Running mutations...", total=len(mutants))

        for mutant in mutants:
            assert mutant.id is not None
            status, output, duration = run_single_mutant(
                mutant, test_command, timeout
            )
            db.update_result(mutant.id, status, output, duration)
            progress.advance(task)
