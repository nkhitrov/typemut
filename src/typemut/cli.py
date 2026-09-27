"""CLI entry point for typemut."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from rich.markup import escape

from typemut.app import App
from typemut.errors import TypemutError

_fail_under_option = click.option(
    "--fail-under",
    type=click.FloatRange(0, 100),
    default=None,
    help="Exit with code 1 if the mutation score (%) is below this value.",
)
_baseline_option = click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="JSON file of accepted survived mutants; exit with code 1 on any other survivor.",
)
_update_baseline_option = click.option(
    "--update-baseline",
    is_flag=True,
    help="Write the current survived mutants to the --baseline file instead of checking it.",
)
_config_option = click.option(
    "--config", "config_path", default="typemut.toml", help="Config file."
)
_jobs_option = click.option("--jobs", default=1, help="Number of parallel jobs.")


class _TypemutGroup(click.Group):
    """Reports a :class:`TypemutError` from any command as a message and exit code 1."""

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except TypemutError as exc:
            app: App = ctx.obj
            app.console.print(f"[red]{escape(exc.message)}[/red]")
            if exc.details:
                app.console.print(escape(exc.details))
            ctx.exit(1)


@click.group(cls=_TypemutGroup)
@click.option(
    "-C",
    "--project-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Change to this directory before running (target project root).",
)
@click.pass_context
def main(ctx: click.Context, project_dir: str | None) -> None:
    """typemut — Mutation testing for type annotations.

    ``ctx.obj`` may carry a factory that builds the :class:`App` for the
    project root (tests pass ``partial(App, runner=stub, ...)``); by default
    the app runs with the real implementations.
    """
    if project_dir:
        os.chdir(project_dir)
    make_app: Callable[[Path], App] = ctx.obj or App
    ctx.obj = make_app(Path.cwd())


@main.command()
@_config_option
@click.option("--db", "db_path", default=None, help="Database file.")
@click.pass_obj
def init(
    app: App,
    config_path: str,
    db_path: str | None,  # pragma: no mutate  (click passes None when --db is omitted)
) -> None:
    """Discover all possible mutations and store in database."""
    cfg, db = app.load(config_path, db_path)
    with db:
        app.discover(cfg, db)


@main.command("exec")
@_config_option
@click.option("--db", "db_path", default=None, help="Database file.")
@_jobs_option
@click.pass_obj
def exec_cmd(
    app: App,
    config_path: str,
    db_path: str | None,  # pragma: no mutate  (click passes None when --db is omitted)
    jobs: int,
) -> None:
    """Run type checker against each mutation."""
    cfg, db = app.load(config_path, db_path)
    with db:
        app.execute(cfg, db, jobs)
    app.console.print("[green]Done.[/green]")


@main.command()
@click.option("--db", "db_path", default=None, help="Database file [default: typemut.sqlite].")
@_fail_under_option
@_baseline_option
@_update_baseline_option
@click.pass_obj
def report(
    app: App,
    db_path: str | None,  # pragma: no mutate  (click passes None when --db is omitted)
    fail_under: float | None,
    baseline_path: str | None,
    update_baseline: bool,
) -> None:
    """Show mutation testing results."""
    _require_baseline_path(baseline_path, update_baseline)
    with app.open_db(db_path) as db:
        app.report(db)
        passed = app.check_results(db, fail_under, baseline_path, update_baseline)
    _exit_unless(passed)


@main.command()
@click.option("--db", "db_path", default=None, help="Database file [default: typemut.sqlite].")
@click.option("-o", "--output", "out_path", default="typemut-report.html", help="Output file.")
@click.option("--open", "open_browser", is_flag=True, help="Open report in browser.")
@click.pass_obj
def html(
    app: App,
    db_path: str | None,  # pragma: no mutate  (click passes None when --db is omitted)
    out_path: str,
    open_browser: bool,
) -> None:
    """Generate HTML report."""
    with app.open_db(db_path) as db:
        app.write_html(db, Path(out_path), open_browser)


@main.command()
@_config_option
@click.option("--db", "db_path", default=None, help="Database file.")
@_jobs_option
@_fail_under_option
@_baseline_option
@_update_baseline_option
@click.pass_obj
def run(
    app: App,
    config_path: str,
    db_path: str | None,
    jobs: int,
    fail_under: float | None,
    baseline_path: str | None,
    update_baseline: bool,
) -> None:
    """Run full pipeline: discover mutations, execute, and report."""
    _require_baseline_path(baseline_path, update_baseline)
    cfg, db = app.load(config_path, db_path)
    with db:
        app.discover(cfg, db)
        app.execute(cfg, db, jobs)
        app.console.print()
        app.report(db)
        passed = app.check_results(db, fail_under, baseline_path, update_baseline)
    _exit_unless(passed)


def _require_baseline_path(baseline_path: str | None, update_baseline: bool) -> None:
    if update_baseline and baseline_path is None:
        raise click.UsageError("--update-baseline requires --baseline")


def _exit_unless(passed: bool) -> None:
    if not passed:
        raise click.exceptions.Exit(1)
