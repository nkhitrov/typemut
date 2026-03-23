"""Tests for registry."""

from __future__ import annotations

from pathlib import Path

from typemut.registry import Registry


def test_hierarchy_from_fixture(fixtures_dir: Path):
    files = [fixtures_dir / "pydantic_models.py"]
    reg = Registry.from_files(files)

    assert "LoanState" in reg.hierarchy
    siblings = reg.get_siblings("ActiveLoan")
    assert "ClosedLoan" in siblings
    assert "OverdueLoan" in siblings
    assert "ActiveLoan" not in siblings


def test_literal_pool(fixtures_dir: Path):
    files = [fixtures_dir / "pydantic_models.py"]
    reg = Registry.from_files(files)

    file_key = str(fixtures_dir / "pydantic_models.py")
    literals = reg.get_file_literals(file_key)
    assert '"active"' in literals or "'active'" in literals


def test_no_siblings_for_unknown():
    reg = Registry()
    assert reg.get_siblings("Unknown") == []
