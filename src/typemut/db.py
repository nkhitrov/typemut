"""SQLite database for mutation results."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

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
    duration_seconds REAL,
    depends TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON mutants(status);
CREATE INDEX IF NOT EXISTS idx_module ON mutants(module_path);

-- Results of earlier runs, kept across ``clear()`` for incremental runs.
-- required_import is '' when there is none: NULLs never collide in a key.
CREATE TABLE IF NOT EXISTS result_cache (
    module_path TEXT NOT NULL,
    line INTEGER NOT NULL,
    col INTEGER NOT NULL,
    operator TEXT NOT NULL,
    original_annotation TEXT NOT NULL,
    mutated_annotation TEXT NOT NULL,
    required_import TEXT NOT NULL,
    status TEXT NOT NULL,
    output TEXT,
    depends TEXT,
    PRIMARY KEY (
        module_path, line, col, operator,
        original_annotation, mutated_annotation, required_import
    )
);

-- The inputs the cached results were computed with: {name: value}.
CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_MIGRATIONS = [
    # Columns missing from DBs created by earlier versions.
    "ALTER TABLE mutants ADD COLUMN required_import TEXT",
    "ALTER TABLE mutants ADD COLUMN depends TEXT",
]

# What identifies a mutant across runs: module path, line, column, operator,
# original and mutated annotation, required import ('' for none).
MutantKey: TypeAlias = tuple[str, int, int, str, str, str, str]


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
    status: str = "pending"
    output: str | None = None
    duration_seconds: float | None = None
    # {project file: sha256} a kill was computed from; None if it cannot be reused.
    depends: Mapping[str, str] | None = None

    def key(self) -> MutantKey:
        """What identifies this mutant across runs."""
        return (
            self.module_path,
            self.line,
            self.col,
            self.operator,
            self.original_annotation,
            self.mutated_annotation,
            self.required_import or "",
        )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self.cache = CacheTables(self.conn)

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
                mutated_annotation, description, required_import, status, depends)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                DependsColumn.dump(mutant.depends),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def insert_many(self, mutants: Iterable[MutantRow]) -> None:
        self.conn.executemany(
            """INSERT INTO mutants
               (module_path, operator, line, col, original_annotation,
                mutated_annotation, description, required_import, status, depends)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    DependsColumn.dump(m.depends),
                )
                for m in mutants
            ],
        )
        self.conn.commit()

    def update_result(
        self,
        mutant_id: int,
        status: str,
        output: str | None = None,
        duration: float | None = None,
    ) -> None:
        self.conn.execute(
            """UPDATE mutants
               SET status = ?, output = ?, duration_seconds = ?
               WHERE id = ?""",
            (status, output, duration, mutant_id),
        )
        self.conn.commit()

    def get_pending(self) -> Collection[MutantRow]:
        rows = self.conn.execute(
            "SELECT * FROM mutants WHERE status = 'pending' ORDER BY id"
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
        """Store the status, output, duration and dependencies of finished mutants."""
        self.conn.executemany(
            """UPDATE mutants
               SET status = ?, output = ?, duration_seconds = ?, depends = ?
               WHERE id = ?""",
            [
                (m.status, m.output, m.duration_seconds, DependsColumn.dump(m.depends), m.id)
                for m in results
            ],
        )
        self.conn.commit()

    def count_pending(self) -> int:
        """Number of mutants not run yet."""
        row = self.conn.execute("SELECT COUNT(*) FROM mutants WHERE status = 'pending'").fetchone()
        return int(row[0])

    def clear(self) -> None:
        """Remove all mutants; the result cache is kept."""
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
            status=row["status"],
            output=row["output"],
            duration_seconds=row["duration_seconds"],
            depends=DependsColumn.load(row),
        )


class CacheTables:
    """The result cache of a database: results of earlier runs, kept by :meth:`Database.clear`.

    Cached results are stored by :class:`MutantKey`, with the inputs (checker,
    its version, lockfiles...) they were computed with as ``{name: value}``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def meta(self) -> Mapping[str, str]:
        """The inputs the cached results were computed with."""
        rows = self._conn.execute("SELECT key, value FROM cache_meta").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def reset(self, meta: Mapping[str, str]) -> None:
        """Drop every cached result and record *meta* as the inputs of the next ones."""
        with self._conn:
            self._conn.execute("DELETE FROM result_cache")
            self._conn.execute("DELETE FROM cache_meta")
            self._conn.executemany(
                "INSERT INTO cache_meta (key, value) VALUES (?, ?)", list(meta.items())
            )

    def upsert(self, mutants: Iterable[MutantRow]) -> None:
        """Store the results of *mutants* in the cache, replacing earlier ones."""
        with self._conn:
            self._conn.executemany(
                """INSERT OR REPLACE INTO result_cache
                   (module_path, line, col, operator, original_annotation,
                    mutated_annotation, required_import, status, output, depends)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(*m.key(), m.status, m.output, DependsColumn.dump(m.depends)) for m in mutants],
            )

    def load(self) -> Mapping[MutantKey, MutantRow]:
        """Cached results by mutant key, as rows without an id or description."""
        rows = self._conn.execute("SELECT * FROM result_cache").fetchall()
        cached = (
            MutantRow(
                id=None,
                module_path=row["module_path"],
                operator=row["operator"],
                line=row["line"],
                col=row["col"],
                original_annotation=row["original_annotation"],
                mutated_annotation=row["mutated_annotation"],
                description="",
                required_import=row["required_import"] or None,
                status=row["status"],
                output=row["output"],
                depends=DependsColumn.load(row),
            )
            for row in rows
        )
        return {mutant.key(): mutant for mutant in cached}


class DependsColumn:
    """``MutantRow.depends`` as stored: a JSON object, or NULL."""

    @staticmethod
    def dump(depends: Mapping[str, str] | None) -> str | None:
        return None if depends is None else json.dumps(dict(depends), sort_keys=True)

    @staticmethod
    def load(row: sqlite3.Row) -> Mapping[str, str] | None:
        """The ``depends`` column of *row*."""
        text = row["depends"]
        return None if text is None else dict(json.loads(text))
