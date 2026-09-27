"""Tests for terminal and HTML report generation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from tests.fakes import StubSourceReader
from typemut.db import Database, MutantRow
from typemut.reporting.html import FileSourceReader, HtmlReport
from typemut.reporting.terminal import MutationScore, TerminalReport


def _populate_db(db: Database) -> None:
    db.insert_many([
        MutantRow(None, "a.py", "RemoveUnionMember", 1, 3, "int | str", "int", "Remove str", status="killed"),
        MutantRow(None, "a.py", "AddOptional", 2, 3, "int", "int | None", "Add None", status="survived"),
        MutantRow(None, "b.py", "RemoveOptional", 1, 3, "int | None", "int", "Remove None", status="killed"),
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
        assert "0.0%" in html

    def test_html_contains_modules(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = HtmlReport().render(tmp_db)
        assert "a.py" in html
        assert "b.py" in html
        assert "TOTAL" in html

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
        mutant_id = tmp_db.insert_mutant(
            MutantRow(None, "a.py", "AddOptional", 1, 3, "int", "int | None", "")
        )
        tmp_db.update_result(mutant_id, "killed", "error <here>", 0.5)
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
