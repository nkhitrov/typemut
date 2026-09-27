"""Mutation execution: apply a mutant, run the test command, record the result."""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Collection, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import replace
from pathlib import Path
from typing import Final, Protocol

from rich.console import Console
from rich.progress import track

from typemut.db import Database, MutantRow
from typemut.imports import resolve_import
from typemut.runner import CommandResult, CommandRunner, Outcome

# mypy error codes that indicate the mutated code is broken (missing import,
# syntax error, invalid type) rather than a genuine type-system kill.
FALSE_KILL_CODES: AbstractSet[str] = frozenset(
    {
        "name-defined",  # Name "Sequence" is not defined
        "syntax",  # Syntax error in mutated code
        "valid-type",  # Not valid as a type
    }
)

_ERROR_CODE_RE = re.compile(r"\[(\w[\w-]*)\]\s*$")

# mypy trusts its incremental cache when a file's size and whole-second mtime
# are unchanged. Mutants of one file often have equal sizes and are written
# within the same second, so each mutated file gets an mtime derived from its
# content, up to this many seconds before the original one.
_MTIME_SPREAD_SECONDS = 2**24
_NS_PER_SECOND = 10**9

_DB_FLUSH_BATCH_SIZE = 50


# Mutant status by test-command outcome, before false-kill detection.
_STATUS_BY_OUTCOME: Final = {
    Outcome.PASSED: "survived",  # no type errors: the mutant went unnoticed
    Outcome.FAILED: "killed",
    Outcome.TIMED_OUT: "killed",
}


class MutationApplyError(ValueError):
    """The mutant does not match the current source, so it cannot be applied."""


class MutantExecutor(Protocol):
    """Runs mutants and yields them finished (with status, output, duration), in any order."""

    def execute(self, mutants: Collection[MutantRow]) -> Iterable[MutantRow]:
        """Run every mutant in *mutants*."""
        ...


class ProgressBar(Protocol):
    """Reports progress while results arrive."""

    def track(self, results: Iterable[MutantRow], total: int) -> Iterable[MutantRow]:
        """Yield *results* unchanged, reporting progress towards *total*."""
        ...


class RichProgressBar:
    """Progress bar drawn on a rich console."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def track(self, results: Iterable[MutantRow], total: int) -> Iterable[MutantRow]:
        return track(
            results,
            total=total,
            description="Running mutations...",
            console=self._console,
        )


class MutationTester:
    """Applies one mutant at a time under a project root and runs the test command."""

    def __init__(self, runner: CommandRunner, test_command: str, timeout: int) -> None:
        self.runner = runner
        self.test_command = test_command
        self.timeout = timeout

    def check_baseline(self, root: Path) -> tuple[bool, str]:
        """Run the test command on unmodified code. Returns (ok, output)."""
        result = self.runner.run(self.test_command, timeout=self.timeout, cwd=root)
        if result.outcome is Outcome.TIMED_OUT:
            return False, "Baseline check timed out"
        return result.outcome is Outcome.PASSED, result.output

    def run(self, mutant: MutantRow, root: Path) -> MutantRow:
        """Apply *mutant* to its file under *root*, run the test command, restore the file.

        Returns the mutant with its status, output and duration set.
        """
        file_path = root / mutant.module_path
        original_source = file_path.read_text()
        try:
            mutated_source = apply_mutation(original_source, mutant)
        except MutationApplyError as exc:
            return replace(mutant, status="error", output=str(exc), duration_seconds=0.0)

        original_stat = file_path.stat()
        try:
            file_path.write_text(mutated_source)
        except OSError as exc:
            output = f"Failed to write mutation: {exc}"
            return replace(mutant, status="error", output=output, duration_seconds=0.0)
        os.utime(
            file_path,
            ns=(
                original_stat.st_atime_ns,
                _content_mtime_ns(mutated_source, original_stat.st_mtime_ns),
            ),
        )

        start = time.monotonic()
        try:
            result = self.runner.run(self.test_command, timeout=self.timeout, cwd=root)
            duration = time.monotonic() - start
        finally:
            file_path.write_text(original_source)
            os.utime(file_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        status, output = classify(result)
        return replace(mutant, status=status, output=output, duration_seconds=duration)


class SequentialExecutor:
    """Runs mutants one by one in the project itself."""

    def __init__(self, tester: MutationTester, root: Path) -> None:
        self._tester = tester
        self._root = root

    def execute(self, mutants: Iterable[MutantRow]) -> Iterable[MutantRow]:
        for mutant in mutants:
            yield self._tester.run(mutant, self._root)


def run_mutants(
    db: Database,
    mutants: Collection[MutantRow],
    executor: MutantExecutor,
    progress: ProgressBar,
) -> None:
    """Execute *mutants* and store their results, flushing to *db* in batches."""
    batch: list[MutantRow] = []
    try:
        for result in progress.track(executor.execute(mutants), total=len(mutants)):
            batch.append(result)
            if len(batch) >= _DB_FLUSH_BATCH_SIZE:
                db.update_results_batch(batch)
                batch.clear()
    finally:
        db.update_results_batch(batch)


def apply_mutation(source: str, mutant: MutantRow) -> str:
    """Return *source* with *mutant* applied, adding the import its type needs."""
    source_for_mutation, inserted_at = resolve_import(
        source,
        mutant.mutated_annotation,
        mutant.required_import,
    )
    line_offset = 1 if inserted_at is not None and inserted_at <= mutant.line - 1 else 0

    lines = source_for_mutation.splitlines(keepends=True)
    line_idx = mutant.line - 1 + line_offset
    if line_idx >= len(lines):
        raise MutationApplyError("Line number out of range")

    # Replace at exact offset in the whole source (annotation may span lines)
    col = mutant.col
    orig = mutant.original_annotation
    offset = sum(len(line) for line in lines[:line_idx]) + col
    end = offset + len(orig)
    found = source_for_mutation[offset:end]
    if found != orig:
        raise MutationApplyError(
            f"Could not apply mutation — expected '{orig}' at col {col}, found '{found}'"
        )
    return source_for_mutation[:offset] + mutant.mutated_annotation + source_for_mutation[end:]


def classify(result: CommandResult) -> tuple[str, str]:
    """Mutant status and output for the test command's *result*.

    A failure whose error codes are all in :data:`FALSE_KILL_CODES` comes from
    broken mutated code (missing import, syntax error), not from the type
    system: it is an error, not a kill.
    """
    if result.outcome is Outcome.TIMED_OUT:
        return "killed", "timeout"
    status = _STATUS_BY_OUTCOME[result.outcome]
    codes = error_codes(result.output)
    if status == "killed" and codes <= FALSE_KILL_CODES and codes:
        return "error", result.output
    return status, result.output


def error_codes(output: str) -> AbstractSet[str]:
    """mypy error codes (``[arg-type]``, ...) that end lines of *output*."""
    return {
        match.group(1)
        for line in output.splitlines()
        if (match := _ERROR_CODE_RE.search(line)) is not None
    }


def _content_mtime_ns(source: str, original_mtime_ns: int) -> int:
    """A whole-second mtime before *original_mtime_ns* that depends only on *source*."""
    digest = hashlib.sha256(source.encode()).digest()
    offset = 1 + int.from_bytes(digest[:8]) % _MTIME_SPREAD_SECONDS
    return (original_mtime_ns // _NS_PER_SECOND - offset) * _NS_PER_SECOND
