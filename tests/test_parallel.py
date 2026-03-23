"""Tests for parallel execution."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from typemut.db import MutantRow
from typemut.parallel import (
    DirtyWorkingTreeError,
    ensure_clean_git_status,
    partition_mutants,
)


def _make_mutant(mid: int, module: str) -> MutantRow:
    return MutantRow(
        id=mid,
        module_path=module,
        operator="Op",
        line=1,
        col=0,
        original_annotation="int",
        mutated_annotation="str",
        description="test",
    )


class TestPartitionMutants:
    def test_single_worker(self) -> None:
        mutants = [_make_mutant(i, f"f{i}.py") for i in range(5)]
        chunks = partition_mutants(mutants, 1)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_even_split(self) -> None:
        mutants = [_make_mutant(i, f"f{i}.py") for i in range(4)]
        chunks = partition_mutants(mutants, 2)
        assert len(chunks) == 2
        total = sum(len(c) for c in chunks)
        assert total == 4

    def test_groups_by_file(self) -> None:
        mutants = [
            _make_mutant(1, "a.py"),
            _make_mutant(2, "a.py"),
            _make_mutant(3, "b.py"),
            _make_mutant(4, "b.py"),
        ]
        chunks = partition_mutants(mutants, 2)
        # Each chunk should contain mutations from the same file
        for chunk in chunks:
            if chunk:
                modules = {m.module_path for m in chunk}
                assert len(modules) == 1

    def test_more_workers_than_mutants(self) -> None:
        mutants = [_make_mutant(1, "a.py")]
        chunks = partition_mutants(mutants, 4)
        assert len(chunks) == 4
        non_empty = [c for c in chunks if c]
        assert len(non_empty) == 1
        assert len(non_empty[0]) == 1

    def test_empty_mutants(self) -> None:
        chunks = partition_mutants([], 3)
        assert len(chunks) == 3
        assert all(len(c) == 0 for c in chunks)

    def test_load_balancing(self) -> None:
        """Large file group goes to one worker, smaller groups fill others."""
        mutants = [
            _make_mutant(1, "big.py"),
            _make_mutant(2, "big.py"),
            _make_mutant(3, "big.py"),
            _make_mutant(4, "small1.py"),
            _make_mutant(5, "small2.py"),
        ]
        chunks = partition_mutants(mutants, 2)
        sizes = sorted(len(c) for c in chunks)
        assert sizes == [2, 3]


class TestEnsureCleanGitStatus:
    def test_clean_repo(self, tmp_path: Path) -> None:
        """Should not raise in a clean git repo."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        # Run ensure_clean_git_status from the clean repo dir
        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ensure_clean_git_status()  # should not raise
        finally:
            os.chdir(old_cwd)

    def test_dirty_repo_uncommitted(self, tmp_path: Path) -> None:
        """Should raise when there are uncommitted changes."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        (tmp_path / "dirty.py").write_text("x = 1\n")

        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(DirtyWorkingTreeError, match="uncommitted"):
                ensure_clean_git_status()
        finally:
            os.chdir(old_cwd)
