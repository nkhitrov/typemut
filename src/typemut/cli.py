"""CLI entry point for typemut."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

from typemut.config import Config, load_config
from typemut.db import Database, MutantRow
from typemut.discovery import discover_annotations, discover_files

if TYPE_CHECKING:
    from typemut.operators.base import TypeMutationOperator
    from typemut.registry import Registry

console = Console()


@click.group()
@click.option(
    "-C",
    "--project-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Change to this directory before running (target project root).",
)
@click.pass_context
def main(ctx: click.Context, project_dir: str | None) -> None:
    """typemut — Mutation testing for type annotations."""
    import os

    if project_dir:
        os.chdir(project_dir)


@main.command()
@click.option("--config", "config_path", default="typemut.toml", help="Config file.")
@click.option("--db", "db_path", default=None, help="Database file.")
def init(config_path: str, db_path: str | None) -> None:
    """Discover all possible mutations and store in database."""
    cfg, db = _load(config_path, db_path)

    from typemut.operators import get_enabled_operators
    from typemut.registry import Registry

    module_dir = Path(cfg.module_path)
    if not module_dir.exists():
        console.print(f"[red]Module path not found: {module_dir}[/red]")
        raise SystemExit(1)

    files = discover_files(module_dir, cfg.excluded_modules)
    console.print(f"Found [bold]{len(files)}[/bold] Python files in {module_dir}")

    registry = Registry.from_files(files)
    operators = get_enabled_operators(cfg.operators)
    console.print(f"Enabled operators: {', '.join(op.name for op in operators)}")

    total = _discover_mutations(files, cfg, operators, registry, db)

    console.print(
        f"[green]Found {total} type annotation mutations across {len(files)} modules[/green]"
    )
    db.close()


@main.command("exec")
@click.option("--config", "config_path", default="typemut.toml", help="Config file.")
@click.option("--db", "db_path", default=None, help="Database file.")
@click.option("--jobs", default=1, help="Number of parallel jobs.")
def exec_cmd(config_path: str, db_path: str | None, jobs: int) -> None:
    """Run type checker against each mutation."""
    cfg, db = _load(config_path, db_path)

    from typemut.engine import check_baseline, run_all_mutants

    pending = db.get_pending()
    if not pending:
        console.print("[yellow]No pending mutants. Run 'typemut init' first.[/yellow]")
        db.close()
        return

    console.print("Running baseline check...")
    ok, output = check_baseline(cfg.test_command, cfg.timeout)
    if not ok:
        console.print(
            "[red]Baseline check failed — type checker reports errors on unmodified code:[/red]"
        )
        console.print(output)
        db.close()
        raise SystemExit(1)
    console.print("[green]Baseline clean.[/green]")

    console.print(f"Running [bold]{len(pending)}[/bold] mutations...")
    if jobs > 1:
        from typemut.parallel import run_all_mutants_parallel

        run_all_mutants_parallel(db, pending, cfg.test_command, cfg.timeout, jobs)
    else:
        run_all_mutants(db, pending, cfg.test_command, cfg.timeout)
    db.close()
    console.print("[green]Done.[/green]")


@main.command()
@click.option("--db", "db_path", default="typemut.sqlite", help="Database file.")
def report(db_path: str) -> None:
    """Show mutation testing results."""
    db = Database(Path(db_path))

    from typemut.reporting.terminal import print_report

    print_report(db, console)
    db.close()


@main.command()
@click.option("--db", "db_path", default="typemut.sqlite", help="Database file.")
@click.option("-o", "--output", "out_path", default=None, help="Output file (default: stdout).")
@click.option("--open", "open_browser", is_flag=True, help="Open report in browser.")
def html(db_path: str, out_path: str | None, open_browser: bool) -> None:
    """Generate HTML report."""
    db = Database(Path(db_path))

    from typemut.reporting.html import generate_html

    report = generate_html(db)
    db.close()

    if out_path:
        Path(out_path).write_text(report)
        console.print(f"Report saved to [bold]{out_path}[/bold]")
    else:
        out_path = "typemut-report.html"
        Path(out_path).write_text(report)
        console.print(f"Report saved to [bold]{out_path}[/bold]")

    if open_browser:
        import webbrowser

        webbrowser.open(f"file://{Path(out_path).resolve()}")


@main.command()
@click.option("--config", "config_path", default="typemut.toml", help="Config file.")
@click.option("--db", "db_path", default=None, help="Database file.")
@click.option("--jobs", default=1, help="Number of parallel jobs.")
def run(config_path: str, db_path: str | None, jobs: int) -> None:
    """Run full pipeline: discover mutations, execute, and report."""
    from typemut.engine import check_baseline, run_all_mutants
    from typemut.operators import get_enabled_operators
    from typemut.registry import Registry
    from typemut.reporting.terminal import print_report

    cfg, db = _load(config_path, db_path)

    module_dir = Path(cfg.module_path)
    if not module_dir.exists():
        console.print(f"[red]Module path not found: {module_dir}[/red]")
        raise SystemExit(1)

    files = discover_files(module_dir, cfg.excluded_modules)
    console.print(f"Found [bold]{len(files)}[/bold] Python files in {module_dir}")

    registry = Registry.from_files(files)
    operators = get_enabled_operators(cfg.operators)
    console.print(f"Enabled operators: {', '.join(op.name for op in operators)}")

    total = _discover_mutations(files, cfg, operators, registry, db)

    console.print(f"[green]Discovered {total} mutations[/green]")

    if total == 0:
        console.print("[yellow]Nothing to test.[/yellow]")
        db.close()
        return

    # Baseline check
    console.print("Running baseline check...")
    ok, output = check_baseline(cfg.test_command, cfg.timeout)
    if not ok:
        console.print(
            "[red]Baseline check failed — type checker reports errors on unmodified code:[/red]"
        )
        console.print(output)
        db.close()
        raise SystemExit(1)
    console.print("[green]Baseline clean.[/green]")

    # Exec
    pending = db.get_pending()
    console.print(f"Running [bold]{len(pending)}[/bold] mutations...")
    if jobs > 1:
        from typemut.parallel import run_all_mutants_parallel

        run_all_mutants_parallel(db, pending, cfg.test_command, cfg.timeout, jobs)
    else:
        run_all_mutants(db, pending, cfg.test_command, cfg.timeout)

    # Report
    console.print()
    print_report(db, console)
    db.close()


def _load(config_path: str, db_path: str | None) -> tuple[Config, Database]:
    path = Path(config_path)
    if not path.exists():
        console.print(
            f"[red]Config file not found: {path}[/red]\n"
            "Create a [bold]typemut.toml[/bold] with at least:\n\n"
            "  [typemut]\n"
            '  module-path = "src"\n'
            '  test-command = "mypy src/"'
        )
        raise SystemExit(1)

    try:
        cfg = load_config(path)
    except tomllib.TOMLDecodeError as exc:
        console.print(
            f"[red]Invalid TOML in {path}:[/red] {exc}\nPlease fix the syntax and try again."
        )
        raise SystemExit(1) from None

    db = Database(Path(db_path or cfg.db_path))
    return cfg, db


def _discover_mutations(
    files: list[Path],
    cfg: Config,
    operators: list[TypeMutationOperator],
    registry: Registry,
    db: Database,
) -> int:
    """Discover mutations across files and insert into database.

    Returns the total number of mutations found.
    """
    db.clear()
    total = 0

    for py_file in files:
        annotations = discover_annotations(py_file, skip_comments=cfg.skip_comments)
        mutants: list[MutantRow] = []

        for ann in annotations:
            for op in operators:
                for mutation in op.find_mutations(ann.node, ann.context, registry):
                    mutants.append(
                        MutantRow(
                            id=None,
                            module_path=str(py_file),
                            operator=mutation.operator,
                            line=mutation.line,
                            col=mutation.col,
                            original_annotation=mutation.original,
                            mutated_annotation=mutation.mutated,
                            description=mutation.description,
                            required_import=mutation.required_import,
                        )
                    )

        if mutants:
            db.insert_many(mutants)
            total += len(mutants)

    return total
