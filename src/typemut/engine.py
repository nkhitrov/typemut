"""Mutation execution loop."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from rich.progress import Progress

from typemut.db import Database, MutantRow
from typemut.imports import resolve_import

# mypy error codes that indicate the mutated code is broken (missing import,
# syntax error, invalid type) rather than a genuine type-system kill.
FALSE_KILL_CODES: frozenset[str] = frozenset(
    {
        "name-defined",  # Name "Sequence" is not defined
        "syntax",  # Syntax error in mutated code
        "valid-type",  # Not valid as a type
    }
)

_ERROR_CODE_RE = re.compile(r"\[(\w[\w-]*)\]\s*$")


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
            status, output, duration = run_single_mutant(mutant, test_command, timeout)
            db.update_result(mutant.id, status, output, duration)
            progress.advance(task)


def run_single_mutant(
    mutant: MutantRow,
    test_command: str,
    timeout: int,
    project_root: Path | None = None,
) -> tuple[str, str | None, float]:
    """Run a single mutation, return (status, output, duration)."""
    base = project_root or Path()
    file_path = base / mutant.module_path
    original_source = file_path.read_text()

    # --- Import injection: add import for the mutated type if needed --------
    source_for_mutation, inserted_at = resolve_import(
        original_source,
        mutant.mutated_annotation,
        mutant.required_import,
    )
    line_offset = 1 if inserted_at is not None and inserted_at < mutant.line - 1 else 0

    # Find and replace the annotation at the correct position
    lines = source_for_mutation.splitlines(keepends=True)
    line_idx = mutant.line - 1 + line_offset

    if line_idx >= len(lines):
        return "error", "Line number out of range", 0.0

    line = lines[line_idx]
    # Replace at exact column position
    col = mutant.col
    orig = mutant.original_annotation
    end_col = col + len(orig)
    if line[col:end_col] != orig:
        return (
            "error",
            f"Could not apply mutation — expected '{orig}' at col {col}, found '{line[col:end_col]}'",
            0.0,
        )
    new_line = line[:col] + mutant.mutated_annotation + line[end_col:]

    lines[line_idx] = new_line
    mutated_source = "".join(lines)

    try:
        file_path.write_text(mutated_source)
    except OSError as exc:
        return "error", f"Failed to write mutation: {exc}", 0.0

    start = time.monotonic()

    try:
        result = subprocess.run(
            test_command,
            shell=True,
            timeout=timeout,
            capture_output=True,
            cwd=str(project_root) if project_root else None,
        )
        duration = time.monotonic() - start
        # exit 0 = no type errors = mutant SURVIVED (bad)
        # exit != 0 = type errors = mutant KILLED (good)
        killed = result.returncode != 0
        status = "killed" if killed else "survived"
        output = result.stderr.decode(errors="replace")
        if not output:
            output = result.stdout.decode(errors="replace")
        if status == "killed" and output and _is_false_kill(output):
            status = "error"
        return status, output, duration
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return "killed", "timeout", duration
    finally:
        file_path.write_text(original_source)


def _is_false_kill(output: str) -> bool:
    """Check if type-checker output indicates a false kill.

    A false kill happens when the mutated code is broken (e.g. missing import,
    syntax error) rather than genuinely caught by the type system.

    Returns True if ALL error codes found in the output belong to
    FALSE_KILL_CODES — meaning there are no real type errors, only
    infrastructure failures.
    """
    found_codes: set[str] = set()
    for line in output.splitlines():
        m = _ERROR_CODE_RE.search(line)
        if m:
            found_codes.add(m.group(1))

    if not found_codes:
        return False

    return found_codes.issubset(FALSE_KILL_CODES)
