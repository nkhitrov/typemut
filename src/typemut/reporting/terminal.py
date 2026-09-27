"""Terminal table report."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from typemut.db import Database, MutantStatus
from typemut.reporting.score import MutationScore


class TerminalReport:
    """Results table printed on a rich *console*."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def print(self, db: Database) -> None:
        """Print mutation testing results as a rich table."""
        summary = db.get_summary()
        if not summary:
            self._console.print("[yellow]No results found.[/yellow]")
            return

        table = Table(title="Type Mutation Testing Report")
        table.add_column("Module", style="cyan")
        table.add_column("Mutants", justify="right")
        table.add_column("Killed", justify="right", style="green")
        table.add_column("Survived", justify="right", style="red")
        table.add_column("Score", justify="right", style="bold")

        total_killed = 0
        total_survived = 0
        total_all = 0

        for module, statuses in sorted(summary.items()):
            killed = statuses.get(MutantStatus.KILLED, 0)
            survived = statuses.get(MutantStatus.SURVIVED, 0)
            pending = statuses.get(MutantStatus.PENDING, 0)
            skipped = statuses.get(MutantStatus.SKIPPED, 0)
            error = statuses.get(MutantStatus.ERROR, 0)
            module_total = killed + survived + pending + skipped + error
            score = (killed / (killed + survived) * 100) if (killed + survived) > 0 else 0

            table.add_row(
                module,
                str(module_total),
                str(killed),
                str(survived),
                f"{score:.1f}%",
            )
            total_killed += killed
            total_survived += survived
            total_all += module_total

        score_total = MutationScore(summary).total() or 0
        table.add_section()
        table.add_row(
            "TOTAL",
            str(total_all),
            str(total_killed),
            str(total_survived),
            f"{score_total:.1f}%",
        )

        self._console.print(table)

        # Show survived mutants
        all_mutants = db.get_all()
        survived_mutants = [m for m in all_mutants if m.status is MutantStatus.SURVIVED]
        if survived_mutants:
            self._console.print("\n[bold red]Survived mutants:[/bold red]")
            for m in survived_mutants:
                self._console.print(
                    f"  {m.module_path}:{m.line}  {m.operator}  "
                    f"{m.original_annotation} → {m.mutated_annotation}"
                )
