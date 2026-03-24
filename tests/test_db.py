"""Tests for database operations."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typemut.db import Database, MutantRow


def test_insert_and_retrieve():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db = Database(Path(f.name))

    mutant = MutantRow(
        id=None,
        module_path="test.py",
        operator="RemoveUnionMember",
        line=10,
        col=3,
        original_annotation="int | str",
        mutated_annotation="int",
        description="Remove str from union",
    )
    mid = db.insert_mutant(mutant)
    assert mid == 1

    pending = db.get_pending()
    assert len(pending) == 1
    assert pending[0].operator == "RemoveUnionMember"
    db.close()


def test_update_result():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db = Database(Path(f.name))

    mutant = MutantRow(
        id=None,
        module_path="test.py",
        operator="RemoveOptional",
        line=5,
        col=3,
        original_annotation="int | None",
        mutated_annotation="int",
        description="Remove None",
    )
    mid = db.insert_mutant(mutant)
    db.update_result(mid, "killed", "type error found", 1.5)

    all_m = db.get_all()
    assert all_m[0].status == "killed"
    assert all_m[0].duration_seconds == 1.5

    pending = db.get_pending()
    assert len(pending) == 0
    db.close()


def test_summary():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db = Database(Path(f.name))

    db.insert_many([
        MutantRow(None, "a.py", "Op1", 1, 3, "int", "str", "desc", status="killed"),
        MutantRow(None, "a.py", "Op2", 2, 3, "str", "int", "desc", status="survived"),
        MutantRow(None, "b.py", "Op1", 1, 3, "int", "str", "desc", status="killed"),
    ])

    summary = db.get_summary()
    assert summary["a.py"]["killed"] == 1
    assert summary["a.py"]["survived"] == 1
    assert summary["b.py"]["killed"] == 1
    db.close()
