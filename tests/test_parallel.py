"""Tests for parallel execution in git worktrees."""

from __future__ import annotations

import hashlib
import subprocess
from multiprocessing import Queue
from pathlib import Path

import pytest

from tests.fakes import StubRunner, make_mutant
from typemut.cache import KillDependencies
from typemut.checkers.mypy import MypyChecker
from typemut.db import MutantRow
from typemut.engine import Deadline, MutationTester
from typemut.parallel import (
    DirtyWorkingTreeError,
    FileGroupPartitioner,
    GitWorkspace,
    InlinePool,
    ProcessPool,
    WorkerError,
    WorkerJob,
    WorkspaceError,
    WorktreeExecutor,
)
from typemut.runner import CommandResult, Outcome, ShellRunner

# In a root holding a `slow` file: mark itself started and hang.
# Elsewhere: survive as soon as the slow worker has started.
_SLOW_IN_MARKED_ROOT = (
    "if [ -f slow ]; then touch started; sleep 30; "
    "else until [ -f ../slow/started ]; do sleep 0.01; done; fi"
)


def _tester(command: str = "true") -> MutationTester:
    return MutationTester(ShellRunner(), command, timeout=60)


def _project(root: Path) -> Path:
    root.mkdir(exist_ok=True)
    (root / "test.py").write_text("x: int = 5\n")
    return root


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=True, text=True
    )
    return completed.stdout


def _git_project(root: Path) -> Path:
    _project(root)
    _git(root, "init")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "test.py")
    _git(root, "commit", "-m", "init")
    return root


def _row_id(row: MutantRow) -> int:
    return row.id or 0


def _statuses(results: list[MutantRow]) -> set[tuple[int | None, str]]:
    return {(result.id, result.status) for result in results}


class TestPartitionMutants:
    def test_single_worker(self) -> None:
        mutants = [make_mutant(i, f"f{i}.py") for i in range(5)]
        chunks = FileGroupPartitioner().split(mutants, 1)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_even_split(self) -> None:
        mutants = [make_mutant(i, f"f{i}.py") for i in range(4)]
        assert [len(chunk) for chunk in FileGroupPartitioner().split(mutants, 2)] == [2, 2]

    def test_groups_by_file(self) -> None:
        mutants = [make_mutant(1, "a.py"), make_mutant(2, "a.py"), make_mutant(3, "b.py")]
        chunks = FileGroupPartitioner().split(mutants, 2)
        assert [[m.module_path for m in chunk] for chunk in chunks] == [["a.py", "a.py"], ["b.py"]]

    def test_more_workers_than_mutants(self) -> None:
        chunks = FileGroupPartitioner().split([make_mutant(1, "a.py")], 4)
        assert [len(chunk) for chunk in chunks] == [1, 0, 0, 0]

    def test_empty_mutants(self) -> None:
        assert FileGroupPartitioner().split([], 3) == [[], [], []]

    def test_load_balancing(self) -> None:
        mutants: list[MutantRow] = [
            make_mutant(1, "big.py"),
            make_mutant(2, "big.py"),
            make_mutant(3, "big.py"),
            make_mutant(4, "small1.py"),
            make_mutant(5, "small2.py"),
        ]
        assert sorted(len(c) for c in FileGroupPartitioner().split(mutants, 2)) == [2, 3]


class TestGitWorkspace:
    def test_clean_repo(self, tmp_path: Path) -> None:
        GitWorkspace(_git_project(tmp_path), ShellRunner()).ensure_clean()

    def test_dirty_repo(self, tmp_path: Path) -> None:
        _git_project(tmp_path)
        (tmp_path / "dirty.py").write_text("x = 1\n")
        with pytest.raises(DirtyWorkingTreeError, match="uncommitted") as exc_info:
            GitWorkspace(tmp_path, ShellRunner()).ensure_clean()
        assert exc_info.value.details == "git status:\n?? dirty.py"

    def test_clean_repo_with_git_warnings(self, tmp_path: Path) -> None:
        result = CommandResult(Outcome.PASSED, stderr="warning: CRLF will be replaced by LF\n")
        GitWorkspace(tmp_path, StubRunner(result)).ensure_clean()

    def test_dirty_repo_with_git_warnings(self, tmp_path: Path) -> None:
        result = CommandResult(Outcome.PASSED, "?? x.py\n", "warning: unsafe repository\n")
        with pytest.raises(DirtyWorkingTreeError, match="uncommitted"):
            GitWorkspace(tmp_path, StubRunner(result)).ensure_clean()

    def test_status_outside_repo(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError, match="Failed to check git status"):
            GitWorkspace(tmp_path, ShellRunner()).ensure_clean()

    def test_create_and_remove_worktree(self, tmp_path: Path) -> None:
        workspace = GitWorkspace(_git_project(tmp_path / "repo"), ShellRunner())

        worktree = workspace.create_worktree(0)
        created = (worktree / "test.py").read_text()
        workspace.remove_worktrees([worktree])

        assert created == "x: int = 5\n"
        assert not worktree.parent.exists()
        assert _git(workspace.root, "worktree", "list").count("\n") == 1

    def test_create_worktree_outside_repo(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError, match="Failed to create git worktree"):
            GitWorkspace(tmp_path, ShellRunner()).create_worktree(0)

    def test_remove_unknown_worktree_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        workspace = GitWorkspace(_git_project(tmp_path / "repo"), ShellRunner())
        unknown = tmp_path / "tmp" / "worktree"
        unknown.mkdir(parents=True)

        workspace.remove_worktrees([unknown])

        assert f"Failed to remove worktree {unknown}" in caplog.text
        assert not unknown.parent.exists()


class TestPools:
    def test_inline_pool(self, tmp_path: Path) -> None:
        jobs = [
            WorkerJob([make_mutant(1)], _project(tmp_path / "a")),
            WorkerJob([make_mutant(2)], _project(tmp_path / "b")),
        ]
        results = list(InlinePool().run(_tester("false"), jobs))
        assert [r.id for r in results] == [1, 2]

    def test_worker_job_puts_results(self, tmp_path: Path) -> None:
        results: Queue[MutantRow] = Queue()
        job = WorkerJob([make_mutant(1), make_mutant(2)], _project(tmp_path))
        job.run(_tester(), results)
        assert _statuses([results.get(), results.get()]) == {(1, "survived"), (2, "survived")}

    def test_process_pool(self, tmp_path: Path) -> None:
        jobs = [
            WorkerJob([make_mutant(1), make_mutant(2)], _project(tmp_path / "a")),
            WorkerJob([], _project(tmp_path / "b")),
            WorkerJob([make_mutant(3)], _project(tmp_path / "c")),
        ]
        results = list(ProcessPool().run(_tester("false"), jobs))
        assert _statuses(results) == {(1, "killed"), (2, "killed"), (3, "killed")}

    def test_process_pool_terminates_workers_when_stopped_early(self, tmp_path: Path) -> None:
        slow = _project(tmp_path / "slow")
        (slow / "slow").write_text("")
        jobs = [
            WorkerJob([make_mutant(1)], _project(tmp_path / "fast")),
            WorkerJob([make_mutant(2)], slow),
        ]
        results = ProcessPool(poll_interval=0.01).run(_tester(_SLOW_IN_MARKED_ROOT), jobs)

        first = next(results)
        results.close()

        assert (first.id, first.status) == (1, "survived")
        assert (slow / "test.py").read_text() == "x: str = 5\n"


    def test_process_pool_fails_when_workers_die(self, tmp_path: Path) -> None:
        jobs = [WorkerJob([make_mutant(1)], tmp_path / "missing")]
        with pytest.raises(WorkerError, match="exited before finishing"):
            list(ProcessPool(poll_interval=0.01).run(_tester(), jobs))


class TestWorktreeExecutor:
    def test_runs_mutants_in_worktrees(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        workspace = GitWorkspace(root, ShellRunner())
        executor = WorktreeExecutor(_tester("grep -q str test.py"), workspace, InlinePool(), 4)

        results = list(executor.execute([make_mutant(1), make_mutant(2, mutated="float")]))

        assert _statuses(results) == {(1, "survived"), (2, "killed")}
        assert _git(root, "worktree", "list").count("\n") == 1
        assert (root / "test.py").read_text() == "x: int = 5\n"

    def test_records_kill_dependencies_in_worker_processes(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        (root / "other.py").write_text("y: int = 5\n")
        _git(root, "add", "other.py")
        _git(root, "commit", "-m", "other")
        tester = MutationTester(
            ShellRunner(),
            "echo 'test.py:1: error: Incompatible types  [assignment]'; false",
            timeout=60,
            dependencies=KillDependencies(MypyChecker()),
            deadline=Deadline(3600.0),
        )
        workspace = GitWorkspace(root, ShellRunner())
        executor = WorktreeExecutor(tester, workspace, ProcessPool(poll_interval=0.01), 2)

        results = list(executor.execute([make_mutant(1), make_mutant(2, "other.py")]))

        test_py = hashlib.sha256(b"x: int = 5\n").hexdigest()
        other_py = hashlib.sha256(b"y: int = 5\n").hexdigest()
        assert [(row.id, row.status, row.depends) for row in sorted(results, key=_row_id)] == [
            (1, "killed", {"test.py": test_py}),
            (2, "killed", {"test.py": test_py, "other.py": other_py}),
        ]

    def test_dirty_tree_is_rejected(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        (root / "test.py").write_text("x: str = 5\n")
        executor = WorktreeExecutor(_tester(), GitWorkspace(root, ShellRunner()), InlinePool(), 2)
        with pytest.raises(DirtyWorkingTreeError):
            list(executor.execute([make_mutant(1)]))
