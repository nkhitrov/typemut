"""Tests for terminal and HTML report generation."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from tests.fakes import StubSourceReader, make_mutant
from typemut.checkers.mypy import MypyChecker
from typemut.db import Database, MutantRow, MutantStatus
from typemut.reporting.html import FileSourceReader, HtmlReport
from typemut.reporting.recurring import RecurringErrorFile, RecurringErrorFinder
from typemut.reporting.score import MutationScore
from typemut.reporting.terminal import TerminalReport


def _populate_db(db: Database) -> None:
    db.insert_many([
        MutantRow(None, "a.py", "RemoveUnionMember", 1, 3, "int | str", "int", "Remove str", status=MutantStatus.KILLED),
        MutantRow(None, "a.py", "AddOptional", 2, 3, "int", "int | None", "Add None", status=MutantStatus.SURVIVED),
        MutantRow(None, "b.py", "RemoveOptional", 1, 3, "int | None", "int", "Remove None", status=MutantStatus.KILLED),
    ])


class TestTerminalReport:
    def test_empty_db(self, tmp_db: Database) -> None:
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        TerminalReport(console).print(tmp_db)
        output = buf.getvalue()
        assert "No results" in output

    def test_report_with_data(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        TerminalReport(console).print(tmp_db)
        output = buf.getvalue()
        assert "a.py" in output
        assert "b.py" in output
        assert "TOTAL" in output

    def test_survived_mutants_shown(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        TerminalReport(console).print(tmp_db)
        output = buf.getvalue()
        assert "Survived" in output


class TestHtmlReport:
    def test_empty_db(self, tmp_db: Database) -> None:
        html = HtmlReport().render(tmp_db)
        assert "typemut" in html
        assert "—" in html
        assert "0.0%" not in html

    def test_html_contains_modules(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = HtmlReport().render(tmp_db)
        assert "a.py" in html
        assert "b.py" in html
        assert "TOTAL" in html

    def test_unscored_module_shows_dash(self, tmp_db: Database) -> None:
        tmp_db.insert_mutant(
            MutantRow(None, "a.py", "AddOptional", 1, 3, "int", "int | None", "", status=MutantStatus.ERROR)
        )
        html = HtmlReport(StubSourceReader({})).render(tmp_db)
        assert '<td class="">—</td></tr>\n' in html

    def test_html_score_calculation(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = HtmlReport().render(tmp_db)
        # 2 killed, 1 survived => 66.7%
        assert "66.7%" in html


class TestHtmlDiff:
    def test_diff_from_source(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        sources = {"a.py": "x: int | str\ny: int\n"}
        html = HtmlReport(StubSourceReader(sources)).render(tmp_db)
        assert '<span class="diff-del">-y: int</span>' in html
        assert '<span class="diff-add">+y: int | None</span>' in html
        assert '<span class="diff-hunk">@@ -1,2 +1,2 @@</span>' in html

    def test_fallback_without_source(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = HtmlReport(StubSourceReader({})).render(tmp_db)
        assert '<div class="diff-add-block"><code>int | None</code></div>' in html

    def test_output_shown(self, tmp_db: Database) -> None:
        mutant = MutantRow(None, "a.py", "AddOptional", 1, 3, "int", "int | None", "")
        mutant_id = tmp_db.insert_mutant(mutant)
        tmp_db.update_results_batch(
            [replace(mutant, id=mutant_id, status=MutantStatus.KILLED, output="error <here>", duration_seconds=0.5)]
        )
        html = HtmlReport(StubSourceReader({})).render(tmp_db)
        assert "<pre>error &lt;here&gt;</pre>" in html


def test_file_source_reader(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x: int\n")
    assert FileSourceReader().read(str(tmp_path / "a.py")) == "x: int\n"
    assert FileSourceReader().read(str(tmp_path / "missing.py")) is None


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ({}, None),
        ({"a.py": {"error": 2, "pending": 1}}, None),
        ({"a.py": {"killed": 3}}, 100.0),
        ({"a.py": {"survived": 2}}, 0.0),
        ({"a.py": {"killed": 1, "survived": 1, "error": 5}, "b.py": {"killed": 2}}, 75.0),
    ],
)
def test_total_score(summary: dict[str, dict[str, int]], expected: float | None) -> None:
    assert MutationScore(summary).total() == expected


def _kill(mutant_id: int, module_path: str, output: str) -> MutantRow:
    return replace(
        make_mutant(mutant_id, module_path), status=MutantStatus.KILLED, output=output
    )


_DOCS_ERROR = "docs/a.py:1: error: Boom  [misc]\n"


class TestRecurringErrorFinder:
    def test_finds_unmutated_file_in_nearly_every_kill(self, tmp_path: Path) -> None:
        kills = [_kill(i, f"src/m{i}.py", f"src/m{i}.py:2: error: X  [misc]\n{_DOCS_ERROR}") for i in range(9)]
        kills.append(_kill(9, "src/m9.py", "src/m9.py:2: error: X  [misc]\n"))
        found = RecurringErrorFinder(MypyChecker()).find(kills, tmp_path)
        assert found == RecurringErrorFile("docs/a.py", 9, 10)
        assert found.percent == 90

    def test_ignores_files_reported_in_few_kills(self, tmp_path: Path) -> None:
        kills = [_kill(i, f"src/m{i}.py", _DOCS_ERROR) for i in range(8)]
        kills += [_kill(i, f"src/m{i}.py", f"src/m{i}.py:2: error: X  [misc]\n") for i in range(2)]
        assert RecurringErrorFinder(MypyChecker()).find(kills, tmp_path) is None

    def test_needs_enough_kills(self, tmp_path: Path) -> None:
        kills = [_kill(i, f"src/m{i}.py", _DOCS_ERROR) for i in range(9)]
        assert RecurringErrorFinder(MypyChecker()).find(kills, tmp_path) is None

    def test_errors_in_the_mutated_file_are_expected(self, tmp_path: Path) -> None:
        kills = [_kill(i, "docs/a.py", _DOCS_ERROR) for i in range(10)]
        assert RecurringErrorFinder(MypyChecker()).find(kills, tmp_path) is None

    def test_counts_only_kills_with_errors(self, tmp_path: Path) -> None:
        kills = [_kill(i, f"src/m{i}.py", _DOCS_ERROR) for i in range(10)]
        others = [
            _kill(10, "src/x.py", "timeout"),
            replace(make_mutant(11, "src/y.py"), status=MutantStatus.SURVIVED, output=_DOCS_ERROR),
        ]
        found = RecurringErrorFinder(MypyChecker()).find([*kills, *others], tmp_path)
        assert found == RecurringErrorFile("docs/a.py", 10, 10)

    def test_absolute_paths_in_root(self, tmp_path: Path) -> None:
        output = f"{tmp_path / 'docs' / 'a.py'}:1: error: Boom  [misc]\n"
        kills = [_kill(i, f"src/m{i}.py", output) for i in range(10)]
        found = RecurringErrorFinder(MypyChecker()).find(kills, tmp_path)
        assert found == RecurringErrorFile("docs/a.py", 10, 10)
