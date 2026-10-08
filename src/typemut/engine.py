"""Mutation execution: apply a mutant, run the test command, record the result."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Collection, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Final, Protocol

from rich.console import Console
from rich.progress import track

from typemut.checkers.base import TypeChecker
from typemut.checkers.generic import GenericChecker
from typemut.db import Database, MutantRow
from typemut.imports import ImportInjector
from typemut.runner import CommandResult, CommandRunner, Outcome

# mypy trusts its incremental cache when a file's size and whole-second mtime
# are unchanged. Mutants of one file often have equal sizes and are written
# within the same second, so each mutated file gets an mtime derived from its
# content, up to this many seconds before the original one.
_MTIME_SPREAD_SECONDS = 2**24
_NS_PER_SECOND = 10**9

DB_FLUSH_BATCH_SIZE = 50


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

    def __init__(
        self,
        runner: CommandRunner,
        test_command: str,
        timeout: int,
        applier: MutationApplier | None = None,
        classifier: OutcomeClassifier | None = None,
    ) -> None:
        self.runner = runner
        self.test_command = test_command
        self.timeout = timeout
        self.applier = applier or MutationApplier()
        self.classifier = classifier or OutcomeClassifier()

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
            mutated_source = self.applier.apply(original_source, mutant)
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
                self._content_mtime_ns(mutated_source, original_stat.st_mtime_ns),
            ),
        )

        start = time.monotonic()
        try:
            result = self.runner.run(self.test_command, timeout=self.timeout, cwd=root)
            duration = time.monotonic() - start
        finally:
            file_path.write_text(original_source)
            os.utime(file_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        status, output = self.classifier.classify(result)
        return replace(mutant, status=status, output=output, duration_seconds=duration)

    def _content_mtime_ns(self, source: str, original_mtime_ns: int) -> int:
        """A whole-second mtime before *original_mtime_ns* that depends only on *source*."""
        digest = hashlib.sha256(source.encode()).digest()
        offset = 1 + int.from_bytes(digest[:8]) % _MTIME_SPREAD_SECONDS
        return (original_mtime_ns // _NS_PER_SECOND - offset) * _NS_PER_SECOND


class SequentialExecutor:
    """Runs mutants one by one in the project itself."""

    def __init__(self, tester: MutationTester, root: Path) -> None:
        self._tester = tester
        self._root = root

    def execute(self, mutants: Iterable[MutantRow]) -> Iterable[MutantRow]:
        for mutant in mutants:
            yield self._tester.run(mutant, self._root)


class MutationApplier:
    """Rewrites a module's source with a mutant applied."""

    def __init__(self, imports: ImportInjector | None = None) -> None:
        self._imports = imports or ImportInjector()

    def apply(self, source: str, mutant: MutantRow) -> str:
        """Return *source* with *mutant* applied, adding the import its type needs."""
        source_for_mutation, inserted_at = self._imports.resolve(
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


class OutcomeClassifier:
    """Turns a test command result into a mutant status.

    *checker* reads the error codes in the output; by default the generic
    checker, which reads mypy-style ``[code]`` line endings.
    """

    def __init__(self, checker: TypeChecker | None = None) -> None:
        self._checker = checker or GenericChecker()

    def classify(self, result: CommandResult) -> tuple[str, str]:
        """Mutant status and output for the test command's *result*.

        A failure whose errors are all false kills comes from broken mutated
        code (missing import, syntax error), not from the type system: it is
        an error, not a kill.
        """
        if result.outcome is Outcome.TIMED_OUT:
            return "killed", "timeout"
        status = _STATUS_BY_OUTCOME[result.outcome]
        if status == "killed" and self._checker.is_false_kill(result.stdout, result.stderr):
            return "error", result.output
        return status, result.output


class ResultRecorder:
    """Stores mutant results in *db* as they arrive, in batches of *batch_size*."""

    def __init__(
        self, db: Database, progress: ProgressBar, batch_size: int = DB_FLUSH_BATCH_SIZE
    ) -> None:
        self._db = db
        self._progress = progress
        self._batch_size = batch_size

    def record(self, mutants: Collection[MutantRow], executor: MutantExecutor) -> None:
        """Execute *mutants* and store their results, flushing to the database in batches."""
        batch: list[MutantRow] = []
        try:
            for result in self._progress.track(executor.execute(mutants), total=len(mutants)):
                batch.append(result)
                if len(batch) >= self._batch_size:
                    self._db.update_results_batch(batch)
                    batch.clear()
        finally:
            self._db.update_results_batch(batch)
