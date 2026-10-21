"""Errors that recur across kills: a sign the checker environment differs from the baseline's."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from typemut.checkers.base import TypeChecker
from typemut.db import MutantRow, MutantStatus


@dataclass(frozen=True)
class RecurringErrorFile:
    """A file *kills* of *total* kills with errors report errors in, without mutating it."""

    path: str
    kills: int
    total: int

    @property
    def percent(self) -> float:
        """The share of the kills that report errors in the file, in percent."""
        return 100 * self.kills / self.total


class RecurringErrorFinder:
    """Finds a file that nearly every kill reports errors in, though none mutated it.

    Mutants of different files rarely break one other file each; errors
    that show up in at least *share* of at least *minimum* kills more likely
    come from a checker environment that differs from the baseline check's.
    *checker* reads the files with errors from the stored outputs.
    """

    def __init__(self, checker: TypeChecker, share: float = 0.9, minimum: int = 10) -> None:
        self._checker = checker
        self._share = share
        self._minimum = minimum

    def find(self, mutants: Iterable[MutantRow], root: Path) -> RecurringErrorFile | None:
        """The file reported in the most kills among *mutants* run in *root*, if suspicious."""
        counts: Counter[str] = Counter()
        total = 0
        kills = [mutant for mutant in mutants if mutant.status is MutantStatus.KILLED]
        for kill in kills:
            files = self._error_files(kill, root)
            if len(files) == 0:
                continue
            total += 1
            counts.update(files - {Path(kill.module_path).as_posix()})
        if total < self._minimum or not counts:
            return None
        path, reported = counts.most_common(1)[0]
        if reported < self._share * total:
            return None
        return RecurringErrorFile(path, reported, total)

    def _error_files(self, kill: MutantRow, root: Path) -> set[str]:
        """Files with errors in the stored output of *kill*."""
        files = self._checker.error_files(kill.output or "", "", root)
        return {*files.paths, *files.outside}
