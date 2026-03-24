"""Tests for database operations."""

from __future__ import annotations

from typemut.db import Database, MutantRow


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


def test_update_result(tmp_db: Database) -> None:
    mutant = _make_mutant(operator="RemoveOptional", original_annotation="int | None", mutated_annotation="int")
    mid = tmp_db.insert_mutant(mutant)
    tmp_db.update_result(mid, "killed", "type error found", 1.5)

    all_m = tmp_db.get_all()
    assert all_m[0].status == "killed"
    assert all_m[0].duration_seconds == 1.5

    pending = tmp_db.get_pending()
    assert len(pending) == 0


def test_summary(tmp_db: Database) -> None:
    tmp_db.insert_many([
        MutantRow(None, "a.py", "Op1", 1, 3, "int", "str", "desc", status="killed"),
        MutantRow(None, "a.py", "Op2", 2, 3, "str", "int", "desc", status="survived"),
        MutantRow(None, "b.py", "Op1", 1, 3, "int", "str", "desc", status="killed"),
    ])

    summary = tmp_db.get_summary()
    assert summary["a.py"]["killed"] == 1
    assert summary["a.py"]["survived"] == 1
    assert summary["b.py"]["killed"] == 1


def test_insert_many(tmp_db: Database) -> None:
    mutants = [_make_mutant(line=i) for i in range(10)]
    tmp_db.insert_many(mutants)
    assert len(tmp_db.get_all()) == 10


def test_update_results_batch(tmp_db: Database) -> None:
    tmp_db.insert_many([_make_mutant(line=1), _make_mutant(line=2)])
    all_m = tmp_db.get_all()
    results = [
        (all_m[0].id, "killed", "error output", 0.5),
        (all_m[1].id, "survived", None, 1.0),
    ]
    tmp_db.update_results_batch(results)

    updated = tmp_db.get_all()
    assert updated[0].status == "killed"
    assert updated[1].status == "survived"
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
