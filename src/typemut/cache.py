"""Results of earlier runs, reused by incremental runs while they are still valid."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from importlib import metadata
from pathlib import Path
from typing import Final

from typemut.checkers.base import TypeChecker
from typemut.config import Config
from typemut.db import Database, MutantRow, MutantStatus
from typemut.runner import CommandResult, Outcome

logger = logging.getLogger(__name__)

# Bumped when the meaning of cached results changes; older caches are reset.
CACHE_FORMAT_VERSION: Final = "1"

# Value of a cache input that could not be found out.
UNKNOWN: Final = "unknown"

# Cache input holding the checker's version: reuse needs it known.
CHECKER_VERSION: Final = "checker version"

# Hash of a file that does not exist (or cannot be read).
_MISSING: Final = ""


class FileHasher:
    """sha256 digests of file contents."""

    def digest(self, path: Path) -> str:
        """The hex sha256 of the file at *path*; empty if it cannot be read."""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return _MISSING

    def digests(self, root: Path, paths: Iterable[str]) -> Mapping[str, str]:
        """``{path: digest}`` of *paths*, relative to *root*."""
        return {path: self.digest(root / path) for path in sorted(set(paths))}


class KillDependencies:
    """The project files a kill depends on, with their digests, for reuse in later runs.

    *checker* reads the files with errors from the test command's output
    and the files they import.
    """

    def __init__(self, checker: TypeChecker, hasher: FileHasher | None = None) -> None:
        self._checker = checker
        self._hasher = hasher or FileHasher()

    def depends(
        self, mutant: MutantRow, result: CommandResult, root: Path
    ) -> Mapping[str, str] | None:
        """``{path: digest}`` of the files the kill of *mutant* in *root* depends on.

        The mutated file, the files with errors and the files they import, as
        they are in *root* (unmutated). None unless the checker failed (not
        timed out) and can tell those files.
        """
        if result.outcome is not Outcome.FAILED:
            return None
        files = self._checker.result_dependencies(result.stdout, result.stderr, root)
        if files is None:
            return None
        return self._hasher.digests(root, {*files, mutant.module_path})


class TypemutVersion:
    """What identifies the installed typemut: its version and a hash of its sources.

    Unreleased builds all report version ``0.0.0``, so the sources in
    *package_dir* (by default typemut's own) are hashed too.
    """

    def __init__(
        self,
        package_dir: Path | None = None,
        hasher: FileHasher | None = None,
    ) -> None:
        self._package_dir = package_dir or Path(__file__).parent
        self._hasher = hasher or FileHasher()

    def fingerprint(self) -> str:
        """``<version>+<source hash>``."""
        paths = [
            path.relative_to(self._package_dir).as_posix()
            for path in self._package_dir.rglob("*.py")
        ]
        sources = hashlib.sha256()
        for relative, digest in self._hasher.digests(self._package_dir, paths).items():
            sources.update(f"{relative}\0{digest}\0".encode())
        return f"{metadata.version('typemut')}+{sources.hexdigest()[:16]}"


class CacheInputs:
    """Everything besides project files that kills depend on, as ``{name: value}``.

    The checker, its version, the Python it runs with, its config files, the
    test command and lockfiles: a change to any of them invalidates every
    cached result.
    """

    def __init__(self, root: Path, hasher: FileHasher | None = None) -> None:
        self._root = root
        self._hasher = hasher or FileHasher()

    def meta(self, cfg: Config, checker: TypeChecker, typemut_version: str) -> Mapping[str, str]:
        """The cache inputs of a run with *cfg* and *checker*."""
        meta = {
            "cache format": CACHE_FORMAT_VERSION,
            "typemut version": typemut_version,
            "checker": checker.name,
            CHECKER_VERSION: checker.version(self._root) or UNKNOWN,
            "checker python": checker.python_version(self._root) or UNKNOWN,
            "test-command": cfg.test_command,
            "timeout": str(cfg.timeout),
        }
        for path in checker.config_files(self._root):
            meta["checker config " + self._name(path)] = self._hasher.digest(path)
        for path in self._key_files(cfg.cache_key_files):
            meta["file " + self._name(path)] = self._hasher.digest(path)
        return meta

    def knows_checker_version(
        self, meta: Mapping[str, str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether the checker version is known in *meta*: reuse needs it."""
        return meta.get(CHECKER_VERSION, UNKNOWN) != UNKNOWN

    def _name(self, path: Path) -> str:
        """*path* relative to the project root, or absolute if it lies outside it."""
        if path.is_relative_to(self._root):
            return path.relative_to(self._root).as_posix()
        return path.as_posix()

    def _key_files(self, patterns: Iterable[str]) -> Iterable[Path]:
        """Files in the project root matching any of the glob *patterns*."""
        found = {path for pattern in patterns for path in self._glob(pattern)}
        return sorted(path for path in found if path.is_file())

    def _glob(self, pattern: str) -> Iterable[Path]:
        """Paths matching *pattern*; none, with a warning, if it is not a valid glob."""
        try:
            return list(self._root.glob(pattern))
        except (ValueError, NotImplementedError) as exc:
            logger.warning("Ignoring invalid 'cache-key-files' pattern %r: %s", pattern, exc)
            return []


@dataclass(frozen=True)
class Reuse:
    """Outcome of looking pending mutants up in the cache.

    *reused* are the pending mutants with the cached kill copied in and
    *remaining* the others, left to run; *stale* counts cached kills a file they depend on has changed since, and
    *untraceable* the cached kills that cannot be reused because the
    checker's output did not tell which files they depend on.
    """

    reused: Collection[MutantRow]
    remaining: Collection[MutantRow]
    stale: int = 0
    untraceable: int = 0


class ResultCache:
    """Results of earlier runs stored in *db*, for the project at *root*."""

    def __init__(self, db: Database, root: Path, hasher: FileHasher | None = None) -> None:
        self._db = db
        self._root = root
        self._hasher = hasher or FileHasher()

    def validate(self, meta: Mapping[str, str]) -> str | None:
        """Reset the cache unless it was computed with the inputs *meta*.

        Returns why it was reset (the inputs that changed), or None if it
        is still valid.
        """
        stored = self._db.cache.meta()
        if stored == meta:
            return None
        self._db.cache.reset(meta)
        changed = sorted(key for key in set(stored) | set(meta) if stored.get(key) != meta.get(key))
        if not stored:
            return "no earlier results"
        return ", ".join(changed) + " changed"

    def reuse(self, pending: Iterable[MutantRow]) -> Reuse:
        """The *pending* mutants killed before, with every file the kill depends on unchanged."""
        cached = self._db.cache.load()
        digests: dict[str, str] = {}
        reused: list[MutantRow] = []
        remaining: list[MutantRow] = []
        stale = 0
        untraceable = 0
        for mutant in pending:
            hit = cached.get(mutant.key())
            if hit is None or hit.status is not MutantStatus.KILLED:
                remaining.append(mutant)
                continue
            if hit.depends is None:
                remaining.append(mutant)
                untraceable += 1
            elif self._unchanged(hit.depends, digests):
                reused.append(
                    replace(
                        mutant,
                        status=hit.status,
                        output=hit.output,
                        duration_seconds=0.0,
                        depends=hit.depends,
                    )
                )
            else:
                remaining.append(mutant)
                stale += 1
        return Reuse(reused, remaining, stale, untraceable)

    def save(self, mutants: Iterable[MutantRow]) -> None:
        """Store the results of the finished *mutants*; pending ones are skipped."""
        self._db.cache.upsert(
            mutant for mutant in mutants if mutant.status is not MutantStatus.PENDING
        )

    def carry_over(self, mutants: Iterable[MutantRow]) -> None:
        """Store the kills of *mutants* recorded with the files they depend on.

        For results about to be replaced: a run killed before it stored
        them keeps them. Other results are not stored, so a run that does
        not track dependencies (not incremental) cannot overwrite the kills
        cached by an incremental one.
        """
        self.save(mutant for mutant in mutants if mutant.depends is not None)

    def _unchanged(
        self, depends: Mapping[str, str], digests: dict[str, str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether every file in *depends* still has its digest; *digests* memoizes them."""
        for path, digest in depends.items():
            if path not in digests:
                digests[path] = self._hasher.digest(self._root / path)
            if digests[path] != digest:
                return False
        return True
