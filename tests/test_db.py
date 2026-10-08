"""Tests for database operations."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from typemut.db import Database, MutantRow, MutantStatus


def _make_mutant(**overrides) -> MutantRow:
    defaults = dict(
        id=None,
        module_path="test.py",
        operator="TestOp",
        line=1,
        col=3,
        original_annotation="int",
        mutated_annotation="str",
        description="test mutation",
    )
    defaults.update(overrides)
    return MutantRow(**defaults)


def test_insert_and_retrieve(tmp_db: Database) -> None:
    mutant = _make_mutant(operator="RemoveUnionMember", original_annotation="int | str", mutated_annotation="int")
    mid = tmp_db.insert_mutant(mutant)
    assert mid == 1

    pending = tmp_db.get_pending()
    assert len(pending) == 1
    assert pending[0].operator == "RemoveUnionMember"


def test_summary(tmp_db: Database) -> None:
    tmp_db.insert_many([
        MutantRow(None, "a.py", "Op1", 1, 3, "int", "str", "desc", status=MutantStatus.KILLED),
        MutantRow(None, "a.py", "Op2", 2, 3, "str", "int", "desc", status=MutantStatus.SURVIVED),
        MutantRow(None, "b.py", "Op1", 1, 3, "int", "str", "desc", status=MutantStatus.KILLED),
    ])

    summary = tmp_db.get_summary()
    assert summary["a.py"]["killed"] == 1
    assert summary["a.py"]["survived"] == 1
    assert summary["b.py"]["killed"] == 1


def test_pending_status_read_back(tmp_db: Database) -> None:
    tmp_db.insert_mutant(_make_mutant())
    assert tmp_db.get_pending()[0].status is MutantStatus.PENDING


def test_get_survived(tmp_db: Database) -> None:
    tmp_db.insert_many(
        [
            _make_mutant(line=1, status=MutantStatus.SURVIVED),
            _make_mutant(line=2, status=MutantStatus.KILLED),
            _make_mutant(line=3, status=MutantStatus.SURVIVED),
        ]
    )
    assert [m.line for m in tmp_db.get_survived()] == [1, 3]


def test_insert_many(tmp_db: Database) -> None:
    mutants = [_make_mutant(line=i) for i in range(10)]
    tmp_db.insert_many(mutants)
    assert len(tmp_db.get_all()) == 10


def test_update_results_batch(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(line=1), _make_mutant(line=2)])
    all_m = tmp_db.get_all()
    results = [
        replace(all_m[0], status=MutantStatus.KILLED, output="error output", duration_seconds=0.5),
        replace(all_m[1], status=MutantStatus.SURVIVED, output=None, duration_seconds=1.0),
    ]
    tmp_db.update_results_batch(results)

    updated = tmp_db.get_all()
    assert updated[0].status is MutantStatus.KILLED
    assert updated[1].status is MutantStatus.SURVIVED
    assert len(tmp_db.get_pending()) == 0


def test_clear(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(line=1), _make_mutant(line=2)])
    assert len(tmp_db.get_all()) == 2
    tmp_db.clear()
    assert len(tmp_db.get_all()) == 0


def test_empty_db_operations(tmp_db: Database) -> None:
    assert tmp_db.get_all() == []
    assert tmp_db.get_pending() == []
    assert tmp_db.get_summary() == {}


def test_required_import_stored(tmp_db: Database) -> None:
    mutant = _make_mutant(required_import="from collections.abc import Sequence")
    mid = tmp_db.insert_mutant(mutant)
    row = tmp_db.get_all()[0]
    assert row.required_import == "from collections.abc import Sequence"


def test_depends_stored(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(depends={"b.py": "2", "a.py": "1"}), _make_mutant(line=2)])
    first, second = tmp_db.get_all()
    tmp_db.update_results_batch([replace(second, status="killed", depends={"c.py": "3"})])
    assert [m.depends for m in tmp_db.get_all()] == [{"a.py": "1", "b.py": "2"}, {"c.py": "3"}]
    assert first.depends == {"a.py": "1", "b.py": "2"}


def test_count_pending(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(), _make_mutant(line=2, status="killed")])
    assert tmp_db.count_pending() == 1


def test_mutant_key() -> None:
    mutant = _make_mutant(required_import="import x")
    assert mutant.key() == ("test.py", 1, 3, "TestOp", "int", "str", "import x")
    assert _make_mutant().key() == ("test.py", 1, 3, "TestOp", "int", "str", "")


def test_old_database_gets_depends_column(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE mutants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, module_path TEXT NOT NULL,
            operator TEXT NOT NULL, line INTEGER NOT NULL, col INTEGER NOT NULL DEFAULT 0,
            original_annotation TEXT NOT NULL, mutated_annotation TEXT NOT NULL,
            description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            output TEXT, duration_seconds REAL)"""
    )
    conn.execute(
        "INSERT INTO mutants (module_path, operator, line, original_annotation,"
        " mutated_annotation, description) VALUES ('a.py', 'Op', 1, 'int', 'str', '')"
    )
    conn.commit()
    conn.close()
    with Database(path) as db:
        (mutant,) = db.get_all()
    assert (mutant.required_import, mutant.depends) == (None, None)


def test_cache_kept_by_clear(tmp_db: Database) -> None:
    killed = _make_mutant(status="killed", output="err", depends={"test.py": "1"})
    tmp_db.cache.reset({"checker": "mypy"})
    tmp_db.cache.upsert([killed, _make_mutant(line=2, status="survived")])
    tmp_db.clear()
    cached = tmp_db.cache.load()
    assert tmp_db.cache.meta() == {"checker": "mypy"}
    assert cached[killed.key()] == replace(killed, description="")
    assert cached[_make_mutant(line=2).key()].depends is None


def test_cache_upsert_replaces(tmp_db: Database) -> None:
    mutant = _make_mutant(required_import="import x", status="killed", depends={"a": "1"})
    tmp_db.cache.upsert([mutant])
    tmp_db.cache.upsert([replace(mutant, status="survived", depends=None)])
    assert list(tmp_db.cache.load().values()) == [
        replace(mutant, description="", status="survived", depends=None)
    ]


def test_cache_reset_drops_results(tmp_db: Database) -> None:
    tmp_db.cache.reset({"checker": "mypy", "checker version": "1.0"})
    tmp_db.cache.upsert([_make_mutant(status="killed")])
    tmp_db.cache.reset({"checker": "pyright"})
    assert tmp_db.cache.load() == {}
    assert tmp_db.cache.meta() == {"checker": "pyright"}


def test_cache_reset_drops_dependencies_of_recorded_kills(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(status="killed", depends={"test.py": "1"})])
    tmp_db.cache.reset({"checker": "mypy"})
    (mutant,) = tmp_db.get_all()
    assert (mutant.status, mutant.depends) == ("killed", None)
