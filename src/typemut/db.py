"""SQLite database for mutation results."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SCHEMA = """\
CREATE TABLE IF NOT EXISTS mutants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_path TEXT NOT NULL,
    operator TEXT NOT NULL,
    line INTEGER NOT NULL,
    col INTEGER NOT NULL DEFAULT 0,
    original_annotation TEXT NOT NULL,
    mutated_annotation TEXT NOT NULL,
    description TEXT NOT NULL,
    required_import TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    output TEXT,
    duration_seconds REAL
);

CREATE INDEX IF NOT EXISTS idx_status ON mutants(status);
CREATE INDEX IF NOT EXISTS idx_module ON mutants(module_path);
"""

_MIGRATIONS = [
    # Add required_import column if missing (for DBs created before this version)
    "ALTER TABLE mutants ADD COLUMN required_import TEXT",
]


class MutantStatus(StrEnum):
    """Result of testing a mutant, as stored in the ``status`` column."""

    PENDING = "pending"
    KILLED = "killed"
    SURVIVED = "survived"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class MutantRow:
    id: int | None
    module_path: str
    operator: str
    line: int
    col: int
    original_annotation: str
    mutated_annotation: str
    description: str
    required_import: str | None = None
    status: MutantStatus = MutantStatus.PENDING
    output: str | None = None
    duration_seconds: float | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        for sql in _MIGRATIONS:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    def insert_mutant(self, mutant: MutantRow) -> int:
        cursor = self.conn.execute(
            """INSERT INTO mutants
               (module_path, operator, line, col, original_annotation,
                mutated_annotation, description, required_import, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mutant.module_path,
                mutant.operator,
                mutant.line,
                mutant.col,
                mutant.original_annotation,
                mutant.mutated_annotation,
                mutant.description,
                mutant.required_import,
                mutant.status,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def insert_many(self, mutants: Iterable[MutantRow]) -> None:
        self.conn.executemany(
            """INSERT INTO mutants
               (module_path, operator, line, col, original_annotation,
                mutated_annotation, description, required_import, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    m.module_path,
                    m.operator,
                    m.line,
                    m.col,
                    m.original_annotation,
                    m.mutated_annotation,
                    m.description,
                    m.required_import,
                    m.status,
                )
                for m in mutants
            ],
        )
        self.conn.commit()

    def get_pending(self) -> Collection[MutantRow]:
        rows = self.conn.execute(
            "SELECT * FROM mutants WHERE status = ? ORDER BY id", (MutantStatus.PENDING,)
        ).fetchall()
        return [self._row_to_mutant(r) for r in rows]

    def get_all(self) -> list[MutantRow]:
        rows = self.conn.execute("SELECT * FROM mutants ORDER BY id").fetchall()
        return [self._row_to_mutant(r) for r in rows]

    def get_summary(self) -> dict[str, dict[str, int]]:
        """Return per-module summary: {module: {killed: N, survived: N, ...}}."""
        rows = self.conn.execute(
            """SELECT module_path, status, COUNT(*) as cnt
               FROM mutants GROUP BY module_path, status"""
        ).fetchall()
        summary: dict[str, dict[str, int]] = {}
        for row in rows:
            module = row["module_path"]
            if module not in summary:
                summary[module] = {}
            summary[module][row["status"]] = row["cnt"]
        return summary

    def update_results_batch(
        self,
        results: Iterable[MutantRow],
    ) -> None:
        """Store the status, output and duration of finished mutants."""
        self.conn.executemany(
            """UPDATE mutants
               SET status = ?, output = ?, duration_seconds = ?
               WHERE id = ?""",
            [(m.status, m.output, m.duration_seconds, m.id) for m in results],
        )
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM mutants")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _row_to_mutant(row: sqlite3.Row) -> MutantRow:
        return MutantRow(
            id=row["id"],
            module_path=row["module_path"],
            operator=row["operator"],
            line=row["line"],
            col=row["col"],
            original_annotation=row["original_annotation"],
            mutated_annotation=row["mutated_annotation"],
            description=row["description"],
            required_import=row["required_import"],
            status=MutantStatus(row["status"]),
            output=row["output"],
            duration_seconds=row["duration_seconds"],
        )
