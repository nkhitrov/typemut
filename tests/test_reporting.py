"""Tests for terminal and HTML report generation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from typemut.db import Database, MutantRow
from typemut.reporting.html import generate_html
from typemut.reporting.terminal import print_report


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
        print_report(tmp_db, console)
        output = buf.getvalue()
        assert "No results" in output

    def test_report_with_data(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        print_report(tmp_db, console)
        output = buf.getvalue()
        assert "a.py" in output
        assert "b.py" in output
        assert "TOTAL" in output

    def test_survived_mutants_shown(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)
        print_report(tmp_db, console)
        output = buf.getvalue()
        assert "Survived" in output


class TestHtmlReport:
    def test_empty_db(self, tmp_db: Database) -> None:
        html = generate_html(tmp_db)
        assert "typemut" in html
        assert "0.0%" in html

    def test_html_contains_modules(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = generate_html(tmp_db)
        assert "a.py" in html
        assert "b.py" in html
        assert "TOTAL" in html

    def test_html_score_calculation(self, tmp_db: Database) -> None:
        _populate_db(tmp_db)
        html = generate_html(tmp_db)
        # 2 killed, 1 survived => 66.7%
        assert "66.7%" in html
