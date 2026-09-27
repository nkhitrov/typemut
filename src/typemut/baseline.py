"""Baseline of accepted survived mutants.

A baseline lets a project gate CI on typemut without first killing every
mutant: survivors recorded in the baseline are accepted, only new ones fail.
Entries are matched by the text of the annotation's source line rather than
its number, so edits elsewhere in a file don't invalidate them.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from typemut.db import MutantRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class BaselineEntry:
    file: str
    operator: str
    original: str
    mutated: str
    source: str  # stripped source line the annotation starts on


@dataclass
class BaselineDiff:
    new: list[MutantRow]  # survivors not covered by the baseline
    fixed: int  # baseline entries that no longer survive


class Baseline:
    """The baseline file at *path*."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Counter[BaselineEntry]:
        """Read a baseline file; warn and treat it as empty if it is missing or invalid."""
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring baseline %s: %s", self.path, exc)
            return Counter()
        if not isinstance(raw, list):
            logger.warning("Ignoring baseline %s: expected a JSON list", self.path)
            return Counter()
        entries: Counter[BaselineEntry] = Counter()
        for item in raw:
            entry = self._parse_entry(item)
            if entry is None:
                logger.warning("Skipping invalid baseline entry %r in %s", item, self.path)
                continue
            entries[entry] += 1
        return entries

    def save(self, survivors: Iterable[MutantRow]) -> None:
        """Write *survivors* as the new baseline."""
        entries = sorted(self._entry_for(mutant) for mutant in survivors)
        self.path.write_text(json.dumps([asdict(entry) for entry in entries], indent=2) + "\n")

    def compare(self, survivors: Iterable[MutantRow]) -> BaselineDiff:
        """Split *survivors* into ones the baseline accepts and new ones."""
        remaining = self.load()
        new: list[MutantRow] = []
        for mutant in survivors:
            entry = self._entry_for(mutant)
            if remaining[entry] > 0:
                remaining[entry] -= 1
            else:
                new.append(mutant)
        return BaselineDiff(new=new, fixed=remaining.total())

    def _entry_for(self, mutant: MutantRow) -> BaselineEntry:
        return BaselineEntry(
            file=mutant.module_path,
            operator=mutant.operator,
            original=mutant.original_annotation,
            mutated=mutant.mutated_annotation,
            source=self._source_line(Path(mutant.module_path), mutant.line),
        )

    def _parse_entry(self, item: object) -> BaselineEntry | None:
        names = {field.name for field in fields(BaselineEntry)}
        if not isinstance(item, dict) or set(item) != names:
            return None
        if not all(isinstance(value, str) for value in item.values()):
            return None
        return BaselineEntry(**item)

    def _source_line(self, path: Path, line: int) -> str:
        try:
            lines = path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            return ""
        if not 0 < line <= len(lines):
            return ""
        return lines[line - 1].strip()
