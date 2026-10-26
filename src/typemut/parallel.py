"""Parallel mutation execution in git worktrees."""

from __future__ import annotations

import logging
import queue
import shlex
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from multiprocessing import Process, Queue
from pathlib import Path
from typing import Protocol

from typemut.db import MutantRow
from typemut.engine import MutationTester
from typemut.errors import TypemutError
from typemut.runner import CommandResult, CommandRunner, Outcome
from typemut.signals import TerminateSignal

logger = logging.getLogger(__name__)

# Seconds to wait for a terminated worker to exit.
_TERMINATE_TIMEOUT = 5

# Lines of a failed worktree baseline shown to the user.
_BASELINE_LINES = 20

_WORKTREE_BASELINE_CAUSES = (
    "With --jobs, mutants run in temporary git worktrees of the current commit, "
    "and the type checker sees a different project there. Likely causes:\n"
    "  - the project is installed in editable mode (a .pth file points at the "
    "project root), so the checker treats files under the root as an installed "
    "package, but checks them as project files in a worktree;\n"
    "  - files the checker needs are ignored by git or untracked (generated code, "
    "stubs, local config) and missing from the worktrees;\n"
    "  - test-command or the checker config uses absolute paths into the project root.\n"
    "Every mutant would be killed by these errors, so no mutant was run. Make the "
    "checker pass in a fresh `git worktree add` checkout (e.g. exclude those files "
    "in its config), or run with --jobs 1."
)


class WorkspaceError(TypemutError):
    """A git operation needed for parallel execution failed."""


class WorkerError(TypemutError):
    """A worker process failed."""


class DirtyWorkingTreeError(WorkspaceError):
    """Raised when the git working tree has uncommitted changes."""


class WorktreeBaselineError(TypemutError):
    """The type checker fails on unmodified code in a worktree, though not in the project."""


@dataclass(frozen=True)
class WorkerJob:
    """Mutants that one worker runs, one after another, in its own copy of the project."""

    mutants: Collection[MutantRow]
    root: Path

    def run(self, tester: MutationTester, results: Queue[MutantRow]) -> None:
        """Run the mutants and put each result on *results*."""
        for mutant in self.mutants:
            results.put(tester.run(mutant, self.root))


class WorkerPool(Protocol):
    """Runs worker jobs, possibly concurrently, and yields results as they arrive."""

    def run(self, tester: MutationTester, jobs: Iterable[WorkerJob]) -> Iterable[MutantRow]:
        """Run every job with *tester*."""
        ...


class InlinePool:
    """Runs jobs one after another in the current process."""

    def run(self, tester: MutationTester, jobs: Iterable[WorkerJob]) -> Iterable[MutantRow]:
        for job in jobs:
            for mutant in job.mutants:
                yield tester.run(mutant, job.root)


class ProcessPool:
    """Runs each job in its own process.

    Waits for results *poll_interval* seconds at a time, checking in between
    that some worker is still alive. In the workers *terminate_signal* makes
    SIGTERM end them as usual, even if the parent turned it into
    KeyboardInterrupt and they were forked with that handler.
    """

    def __init__(
        self,
        poll_interval: float = 1.0,
        terminate_signal: TerminateSignal | None = None,
    ) -> None:
        self._poll_interval = poll_interval
        self._terminate_signal = terminate_signal or TerminateSignal()

    def run(self, tester: MutationTester, jobs: Iterable[WorkerJob]) -> Iterable[MutantRow]:
        results: Queue[MutantRow] = Queue()
        active = [job for job in jobs if job.mutants]
        processes = [Process(target=self._work, args=(job, tester, results)) for job in active]
        for process in processes:
            process.start()
        try:
            remaining = sum(len(job.mutants) for job in active)
            while remaining:
                result = self._next_result(results)
                if result is None:
                    if not any(process.is_alive() for process in processes):
                        raise WorkerError("A worker process exited before finishing its mutants")
                    continue
                remaining -= 1
                yield result
            for process in processes:
                process.join()
        finally:
            # Workers are still running if the consumer stopped early.
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=_TERMINATE_TIMEOUT)

    def _work(self, job: WorkerJob, tester: MutationTester, results: Queue[MutantRow]) -> None:
        """Worker process body."""
        self._terminate_signal.ends_process()
        job.run(tester, results)

    def _next_result(self, results: Queue[MutantRow]) -> MutantRow | None:
        """The next result, or None if none arrived within the poll interval."""
        try:
            return results.get(timeout=self._poll_interval)
        except queue.Empty:
            return None


class GitWorkspace:
    """Creates and removes detached git worktrees of the project at *root*.

    Each new worktree gets a copy of the *carry* directories inside *root*
    (e.g. the type checker's cache, which git ignores), so its workers do not
    start cold. Missing ones are skipped, ones outside *root* are skipped
    with a warning.
    """

    def __init__(self, root: Path, runner: CommandRunner, carry: Iterable[Path] = ()) -> None:
        self.root = root
        self._runner = runner
        self._carry = tuple(carry)

    def ensure_clean(self) -> None:
        """Verify the working tree has no uncommitted or untracked files.

        Worktrees only see committed state, so uncommitted changes would be
        silently lost.
        """
        result = self._git("status", "--porcelain")
        if result.outcome is not Outcome.PASSED:
            raise WorkspaceError("Failed to check git status", result.output.strip())
        if result.stdout.strip():
            raise DirtyWorkingTreeError(
                "Working tree has uncommitted changes. "
                "Please commit or stash them before running with --jobs > 1.",
                f"git status:\n{result.output.rstrip()}",
            )

    def create_worktree(self, index: int) -> Path:
        """Create a detached worktree for worker *index* in a new temp directory."""
        worktree = Path(tempfile.mkdtemp(prefix=f"typemut_w{index}_")) / "worktree"
        result = self._git("worktree", "add", "--detach", str(worktree))
        if result.outcome is not Outcome.PASSED:
            shutil.rmtree(worktree.parent, ignore_errors=True)
            raise WorkspaceError("Failed to create git worktree", result.output.strip())
        try:
            for path in self._carry:
                self._copy_into(path, worktree)
        except BaseException:
            # The caller never gets this worktree, so it could not remove it.
            self.remove_worktrees([worktree])
            raise
        return worktree

    def remove_worktrees(self, worktrees: Iterable[Path]) -> None:
        """Remove *worktrees* and their temp directories; failures are only logged."""
        for worktree in worktrees:
            result = self._git("worktree", "remove", "--force", str(worktree))
            if result.outcome is not Outcome.PASSED:
                logger.warning("Failed to remove worktree %s: %s", worktree, result.output.strip())
            shutil.rmtree(worktree.parent, ignore_errors=True)
        self._git("worktree", "prune")

    def _copy_into(self, path: Path, worktree: Path) -> None:
        """Copy the directory *path* of the project to the same place in *worktree*.

        Modification times are kept (mypy drops cache entries whose times
        differ) and symlinks stay symlinks. A missing directory is skipped;
        one outside the project or a failed copy is only logged, the worker
        then starts cold.
        """
        if not path.is_dir():
            return
        if not path.is_relative_to(self.root):
            logger.warning("Not copying %s into worktrees: it is outside %s", path, self.root)
            return
        target = worktree / path.relative_to(self.root)
        try:
            shutil.copytree(
                path, target, symlinks=True, copy_function=shutil.copy2, dirs_exist_ok=True
            )
        except OSError as error:
            logger.warning("Failed to copy %s into worktree %s: %s", path, worktree, error)

    def _git(self, *args: str) -> CommandResult:
        return self._runner.run(shlex.join(("git", *args)), cwd=self.root)


class WorktreeExecutor:
    """Runs mutants on up to *jobs* workers, each in its own git worktree.

    The baseline check, which passed in the project itself, runs again in
    the first worktree before any mutant: a checker that fails there would
    kill every mutant with errors the mutants did not cause. Worktrees are
    checkouts of the same commit with the same carried caches, so one of
    them stands for all, and the check costs one checker run whatever
    *jobs* is (it also warms that worker's cache).
    """

    def __init__(
        self,
        tester: MutationTester,
        workspace: GitWorkspace,
        pool: WorkerPool,
        jobs: int,
        partitioner: FileGroupPartitioner | None = None,
    ) -> None:
        self._partitioner = partitioner or FileGroupPartitioner()
        self._tester = tester
        self._workspace = workspace
        self._pool = pool
        self._jobs = jobs

    def execute(self, mutants: Collection[MutantRow]) -> Iterable[MutantRow]:
        self._workspace.ensure_clean()
        n_workers = min(self._jobs, len(mutants))
        worktrees: list[Path] = []
        try:
            for index in range(n_workers):
                worktrees.append(self._workspace.create_worktree(index))
            for worktree in worktrees[:1]:
                self._check_baseline(worktree)
            jobs = [
                WorkerJob(chunk, root)
                for chunk, root in zip(
                    self._partitioner.split(mutants, n_workers), worktrees, strict=True
                )
            ]
            yield from self._pool.run(self._tester, jobs)
        finally:
            self._workspace.remove_worktrees(worktrees)

    def _check_baseline(self, worktree: Path) -> None:
        """Fail with the likely causes and the first errors if the baseline fails in *worktree*."""
        ok, output = self._tester.check_baseline(worktree)
        if ok:
            return
        lines = output.strip().splitlines()
        shown = lines[:_BASELINE_LINES]
        if len(lines) > len(shown):
            shown.append(f"... ({len(lines) - len(shown)} more lines)")
        raise WorktreeBaselineError(
            "Baseline check passed in the project but fails in a git worktree of it.",
            _WORKTREE_BASELINE_CAUSES + "\n\nFirst errors in the worktree:\n" + "\n".join(shown),
        )


class FileGroupPartitioner:
    """Splits mutants across workers, keeping the mutants of one file together."""

    def split(
        self,
        mutants: Iterable[MutantRow],
        n_workers: int,
    ) -> list[list[MutantRow]]:
        """Split mutants across workers, grouping by file for less I/O."""
        by_file: dict[str, list[MutantRow]] = defaultdict(list)
        for m in mutants:
            by_file[m.module_path].append(m)

        chunks: list[list[MutantRow]] = [[] for _ in range(n_workers)]
        # Sort file groups by size descending for better load balancing
        file_groups = sorted(by_file.values(), key=len, reverse=True)
        for group in file_groups:
            # Assign to the smallest chunk
            smallest = min(range(n_workers), key=lambda i: len(chunks[i]))
            chunks[smallest].extend(group)
        return chunks
