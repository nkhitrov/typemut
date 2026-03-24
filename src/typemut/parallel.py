"""Parallel mutation execution using git worktrees."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from collections import defaultdict
from multiprocessing import Process, Queue
from pathlib import Path

from rich.progress import Progress

from typemut.db import Database, MutantRow
from typemut.engine import run_single_mutant

logger = logging.getLogger(__name__)

_DB_FLUSH_BATCH_SIZE = 50


class DirtyWorkingTreeError(Exception):
    """Raised when the git working tree has uncommitted changes."""


def run_all_mutants_parallel(
    db: Database,
    mutants: list[MutantRow],
    test_command: str,
    timeout: int,
    jobs: int,
) -> None:
    """Run all pending mutants in parallel using git worktrees."""
    ensure_clean_git_status()

    project_root = Path.cwd()
    n_workers = min(jobs, len(mutants))
    worktree_paths: list[Path] = []

    try:
        # Create worktrees
        for i in range(n_workers):
            wt = _create_worktree(project_root, i)
            worktree_paths.append(wt)

        # Partition work
        chunks = partition_mutants(mutants, n_workers)

        # Launch workers
        result_queue: Queue[tuple[int, str, str | None, float]] = Queue()
        processes: list[Process] = []
        for i in range(n_workers):
            if not chunks[i]:
                continue
            p = Process(
                target=_worker_loop,
                args=(
                    chunks[i],
                    str(worktree_paths[i]),
                    test_command,
                    timeout,
                    result_queue,
                ),
            )
            processes.append(p)
            p.start()

        # Collect results with progress bar
        with Progress() as progress:
            task = progress.add_task("Running mutations...", total=len(mutants))
            batch: list[tuple[int, str, str | None, float]] = []
            completed = 0

            while completed < len(mutants):
                item = result_queue.get()
                batch.append(item)
                completed += 1
                progress.advance(task)

                if len(batch) >= _DB_FLUSH_BATCH_SIZE:
                    db.update_results_batch(batch)
                    batch.clear()

            # Flush remaining
            if batch:
                db.update_results_batch(batch)

        for p in processes:
            p.join()

    finally:
        # Terminate any still-running workers
        for p in processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
        _remove_worktrees(project_root, worktree_paths)


def _worker_loop(
    chunk: list[MutantRow],
    worktree_dir: str,
    test_command: str,
    timeout: int,
    result_queue: Queue[tuple[int, str, str | None, float]],
) -> None:
    """Worker process: run mutations in its own worktree."""
    root = Path(worktree_dir)
    for mutant in chunk:
        assert mutant.id is not None
        status, output, duration = run_single_mutant(
            mutant, test_command, timeout, project_root=root
        )
        result_queue.put((mutant.id, status, output, duration))


def ensure_clean_git_status() -> None:
    """Verify git working tree is clean (no uncommitted or untracked files).

    Parallel execution uses git worktrees which only see committed state,
    so uncommitted changes would be silently lost.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DirtyWorkingTreeError(f"Failed to check git status: {result.stderr.strip()}")
    if result.stdout.strip():
        raise DirtyWorkingTreeError(
            "Working tree has uncommitted changes. "
            "Please commit or stash them before running with --jobs > 1.\n"
            f"  git status:\n{result.stdout.rstrip()}"
        )


def _create_worktree(project_root: Path, index: int) -> Path:
    """Create a detached git worktree for a worker."""
    tmp = Path(tempfile.mkdtemp(prefix=f"typemut_w{index}_"))
    worktree_path = tmp / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_path)],
        cwd=str(project_root),
        capture_output=True,
        check=True,
    )
    return worktree_path


def _remove_worktrees(
    project_root: Path,
    worktree_paths: list[Path],
) -> None:
    """Remove git worktrees and their temp directories."""
    for wt in worktree_paths:
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(project_root),
                capture_output=True,
            )
        except Exception:
            logger.warning("Failed to remove worktree %s", wt, exc_info=True)
        # Clean up the parent temp directory
        parent = wt.parent
        if parent.exists():
            shutil.rmtree(parent, ignore_errors=True)
    # Prune stale worktree references
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(project_root),
        capture_output=True,
    )


def partition_mutants(
    mutants: list[MutantRow],
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
