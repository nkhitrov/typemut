"""Tests for the baseline of accepted survived mutants."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from typemut.baseline import BaselineEntry, compare, load_baseline, save_baseline
from typemut.db import MutantRow


def _survivor(module: Path, line: int, mutated: str = "int | None") -> MutantRow:
    return MutantRow(
        id=None,
        module_path=str(module),
        operator="AddOptional",
        line=line,
        col=7,
        original_annotation="int",
        mutated_annotation=mutated,
        description="",
        status="survived",
    )


@pytest.fixture
def module(tmp_path: Path) -> Path:
    path = tmp_path / "app.py"
    path.write_text("class A:\n    x: int\n    y: int\n")
    return path


def test_save_and_load_round_trip(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 3), _survivor(module, 2)])

    assert load_baseline(baseline) == Counter({
        BaselineEntry(str(module), "AddOptional", "int", "int | None", "x: int"): 1,
        BaselineEntry(str(module), "AddOptional", "int", "int | None", "y: int"): 1,
    })


def test_saved_file_is_sorted_json(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 3), _survivor(module, 2)])

    assert [entry["source"] for entry in json.loads(baseline.read_text())] == ["x: int", "y: int"]


def test_compare_accepts_baselined_survivors(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 2)])

    diff = compare([_survivor(module, 2)], load_baseline(baseline))

    assert diff.new == []
    assert diff.fixed == 0


def test_compare_reports_new_and_fixed(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 2)])
    new = _survivor(module, 3)

    diff = compare([new], load_baseline(baseline))

    assert diff.new == [new]
    assert diff.fixed == 1


def test_compare_counts_identical_survivors(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 2)])
    duplicate = _survivor(module, 2)

    diff = compare([_survivor(module, 2), duplicate], load_baseline(baseline))

    assert diff.new == [duplicate]


def test_compare_survives_line_shift(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 2)])
    module.write_text("import os\n\nclass A:\n    x: int\n    y: int\n")

    diff = compare([_survivor(module, 4)], load_baseline(baseline))

    assert diff.new == []


def test_compare_rejects_changed_source_line(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 2)])
    module.write_text("class A:\n    x: int = 0\n    y: int\n")
    survivor = _survivor(module, 2)

    diff = compare([survivor], load_baseline(baseline))

    assert diff.new == [survivor]


def test_save_missing_source_file(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    survivor = _survivor(tmp_path / "gone.py", 1)
    save_baseline(baseline, [survivor])

    assert load_baseline(baseline) == Counter({
        BaselineEntry(str(tmp_path / "gone.py"), "AddOptional", "int", "int | None", ""): 1,
    })


def test_save_line_out_of_range(tmp_path: Path, module: Path) -> None:
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [_survivor(module, 99)])

    assert [entry.source for entry in load_baseline(baseline)] == [""]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"file": "a.py"}',
    ],
)
def test_load_invalid_baseline_is_empty(tmp_path: Path, content: str) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(content)

    assert load_baseline(baseline) == Counter()


def test_load_missing_baseline_is_empty(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "missing.json") == Counter()


def test_load_skips_invalid_entries(tmp_path: Path) -> None:
    valid = {"file": "a.py", "operator": "Op", "original": "int", "mutated": "str", "source": "x"}
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps([valid, {"file": "a.py"}, {**valid, "source": 1}, "x"]))

    assert load_baseline(baseline) == Counter({BaselineEntry(**valid): 1})
