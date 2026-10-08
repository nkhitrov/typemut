"""Application layer: the typemut pipeline behind the CLI commands."""

from __future__ import annotations

import os
import time
import tomllib
import webbrowser
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from typemut.baseline import Baseline
from typemut.cache import (
    CacheInputs,
    KillDependencies,
    ResultCache,
    TypemutVersion,
)
from typemut.checkers import CheckerRegistry
from typemut.checkers.base import TypeChecker
from typemut.config import Config, ConfigLoader
from typemut.db import Database, MutantRow
from typemut.discovery import AnnotationFinder, SourceFiles
from typemut.engine import (
    Deadline,
    MutantExecutor,
    MutationTester,
    OutcomeClassifier,
    ProgressBar,
    ResultRecorder,
    RichProgressBar,
    SequentialExecutor,
)
from typemut.errors import TypemutError
from typemut.ignore import IgnoredTypes
from typemut.operators import OperatorRegistry
from typemut.parallel import GitWorkspace, ProcessPool, WorkerPool, WorktreeExecutor
from typemut.plugins import MutationFinder, PluginRegistry
from typemut.registry import RegistryBuilder
from typemut.reporting.html import HtmlReport
from typemut.reporting.terminal import MutationScore, TerminalReport
from typemut.runner import CommandRunner, ShellRunner
from typemut.signals import TerminateSignal


@dataclass
class App:
    """The typemut pipeline for the project in *root*.

    Every collaborator that talks to the outside world is a field with the
    real implementation as its default; tests build the app with stubs.
    """

    root: Path
    console: Console = field(default_factory=Console)
    runner: CommandRunner = field(default_factory=ShellRunner)
    operators: OperatorRegistry = field(default_factory=OperatorRegistry)
    plugins: PluginRegistry = field(default_factory=PluginRegistry.discover)
    checkers: CheckerRegistry = field(default_factory=CheckerRegistry.discover)
    worker_pool: WorkerPool = field(default_factory=ProcessPool)
    # None draws a rich progress bar on the console.
    progress: ProgressBar | None = None
    open_browser: Callable[[str], object] = webbrowser.open
    config_loader: ConfigLoader = field(default_factory=ConfigLoader)
    registry_builder: RegistryBuilder = field(default_factory=RegistryBuilder)
    html_report: HtmlReport = field(default_factory=HtmlReport)
    # SIGTERM handling while mutants run.
    terminate_signal: TerminateSignal = field(default_factory=TerminateSignal)
    # Seconds for max-duration; the default clock is shared with worker processes.
    clock: Callable[[], float] = time.monotonic
    # What identifies the installed typemut; cached results of another one are dropped.
    typemut_version: str = field(default_factory=TypemutVersion().fingerprint)

    def load(self, config_path: str, db_path: str | None) -> tuple[Config, Database]:
        """Load the config at *config_path* and open the database it (or *db_path*) names."""
        path = Path(config_path)
        if not path.exists():
            raise TypemutError(
                f"Config file not found: {path}",
                "Create a typemut.toml with at least:\n\n"
                "  [typemut]\n"
                '  module-path = "src"\n'
                '  test-command = "mypy src/"',
            )
        try:
            cfg = self.config_loader.load(path)
        except tomllib.TOMLDecodeError as exc:
            raise TypemutError(
                f"Invalid TOML in {path}: {exc}", "Please fix the syntax and try again."
            ) from None
        return cfg, self.open_db(db_path, cfg.db_path)

    def open_db(self, db_path: str | None, default: str = Config.db_path) -> Database:
        """Open the results database at *db_path*, or at *default* when it is None."""
        return Database(Path(db_path or default))

    def discover(self, cfg: Config, db: Database) -> None:
        """Replace the mutants in *db* with all mutations of the configured module.

        The kills already in *db* that an incremental run recorded are kept
        in its result cache first, so the next incremental run can reuse them
        even if the previous one was killed before it saved them there.
        """
        module_dir = Path(cfg.module_path)
        if not module_dir.exists():
            raise TypemutError(f"Module path not found: {module_dir}")

        files = SourceFiles(module_dir, cfg.excluded_modules).find()
        self.console.print(f"Found [bold]{len(files)}[/bold] Python files in {module_dir}")

        plugins = self.plugins.get(cfg.plugins)
        if plugins:
            self.console.print(f"Enabled plugins: {', '.join(plugin.name for plugin in plugins)}")
        operators = self.operators.enabled(cfg.operators)
        operators.extend(op for plugin in plugins for op in plugin.operators())
        self.console.print(f"Enabled operators: {', '.join(op.name for op in operators)}")

        finder = MutationFinder(
            operators,
            self.registry_builder.build(files),
            plugins,
            IgnoredTypes(cfg.ignore_types),
        )
        mutants = self._find_mutants(files, cfg, finder)
        ResultCache(db, self.root).carry_over(db.get_all())
        db.clear()
        db.insert_many(mutants)
        self.console.print(f"[green]Found {len(mutants)} type annotation mutations[/green]")

    def execute(
        self,
        cfg: Config,
        db: Database,
        jobs: int,
        incremental: bool | None = None,
        refresh: bool = False,
        max_duration: float | None = None,
    ) -> None:
        """Check the baseline, then run the pending mutants on *jobs* workers, storing results.

        *incremental* (default: the ``incremental`` option) first takes the
        kills of earlier runs from the result cache, if every file they
        depend on is unchanged, and stores the new results there; *refresh*
        stores them without reusing any. After *max_duration* seconds
        (default: the ``max-duration`` option) no new mutant is started.
        """
        mutants = db.get_pending()
        if len(mutants) == 0:
            self.console.print("[yellow]No pending mutants: nothing to test.[/yellow]")
            return
        deadline = Deadline(cfg.max_duration if max_duration is None else max_duration, self.clock)
        checker = self.checkers.get(
            cfg.checker, cfg.test_command, cfg.checker_version_command, self.runner
        )
        self.console.print("Type checker: " + self._describe(checker))
        if incremental is None:
            incremental = cfg.incremental
        cache = self._open_cache(cfg, db, checker) if incremental or refresh else None
        if cache is not None and refresh:
            self.console.print("Refreshing the result cache: every pending mutant runs.")
        elif cache is not None:
            mutants = self._reuse(db, cache, mutants)
        tester = MutationTester(
            self.runner,
            cfg.test_command,
            cfg.timeout,
            classifier=OutcomeClassifier(checker),
            dependencies=None if cache is None else KillDependencies(checker),
            deadline=deadline,
        )
        self.console.print("Running baseline check...")
        ok, output = tester.check_baseline(self.root)
        if not ok:
            raise TypemutError(
                "Baseline check failed — type checker reports errors on unmodified code:",
                output,
            )
        self.console.print("[green]Baseline clean.[/green]")

        self.console.print(f"Running [bold]{len(mutants)}[/bold] mutations...")
        progress = self.progress or RichProgressBar(self.console)
        ResultRecorder(db, progress, cache=cache).record(
            mutants, self._executor(tester, checker, jobs)
        )
        not_run = db.count_pending()
        if not_run > 0:
            self.console.print(
                f"[yellow]Stopped after max-duration: {not_run} mutants not run.[/yellow]"
            )

    def report(self, db: Database) -> None:
        """Print the results table."""
        TerminalReport(self.console).print(db)

    def check_results(
        self,
        db: Database,
        fail_under: float | None,
        baseline_path: str | None,
        update_baseline: bool,
    ) -> bool:
        """Update or enforce the survivor baseline and enforce *fail_under*.

        Returns False if the run must fail; it does if any mutant was not
        run (a run stopped early or interrupted), and then the baseline is
        not updated.
        """
        not_run = db.count_pending()
        if not_run > 0:
            self.console.print(
                f"[red]{not_run} mutants not run yet (stopped early or interrupted); "
                "run exec again to test them.[/red]"
            )
            return False
        score = MutationScore(db.get_summary()).total()
        survivors = [mutant for mutant in db.get_all() if mutant.status == "survived"]

        if update_baseline and baseline_path is not None:
            Baseline(Path(baseline_path)).save(survivors)
            self.console.print(
                f"Baseline {baseline_path} updated: {len(survivors)} survived mutants"
            )
            return True

        passed = baseline_path is None or self._check_survivor_baseline(
            Path(baseline_path), survivors
        )
        if fail_under is not None and score is not None and score < fail_under:
            self.console.print(
                f"[red]Mutation score {score:.1f}% is below --fail-under {fail_under:g}%[/red]"
            )
            passed = False
        return passed

    def write_html(self, db: Database, out_path: Path, open_browser: bool) -> None:
        """Write the HTML report to *out_path*, optionally opening it in a browser."""
        out_path.write_text(self.html_report.render(db))
        self.console.print(f"Report saved to [bold]{out_path}[/bold]")
        if open_browser:
            self.open_browser(out_path.resolve().as_uri())

    def _check_survivor_baseline(self, path: Path, survivors: Collection[MutantRow]) -> bool:
        """Report survivors missing from the baseline at *path*; True if there are none."""
        diff = Baseline(path).compare(survivors)
        accepted = len(survivors) - len(diff.new)
        self.console.print(
            f"Baseline {path}: {accepted} accepted, {len(diff.new)} new survived mutants"
        )
        if diff.fixed:
            self.console.print(
                f"[yellow]{diff.fixed} baseline entries no longer survive; "
                "rerun with --update-baseline to drop them.[/yellow]"
            )
        for mutant in diff.new:
            self.console.print(
                f"  [red]new[/red] {mutant.module_path}:{mutant.line}  {mutant.operator}  "
                f"{escape(mutant.original_annotation)} → {escape(mutant.mutated_annotation)}"
            )
        return not diff.new

    def _open_cache(self, cfg: Config, db: Database, checker: TypeChecker) -> ResultCache | None:
        """The result cache in *db*, reset unless it was computed with this run's inputs.

        None when this run can neither reuse nor store results: *checker*
        cannot tell which files a kill depends on, or its version is unknown
        (the cache is then left as it is for the next run that knows it).
        """
        if not checker.traces_dependencies:
            self.console.print(
                f"[yellow]{checker.name} checker: kills are never reused "
                "(it cannot trace their files).[/yellow]"
            )
            return None
        inputs = CacheInputs(self.root)
        meta = inputs.meta(cfg, checker, self.typemut_version)
        if not inputs.knows_checker_version(meta):
            self.console.print(
                f"[yellow]{checker.name} version unknown: result cache not used "
                "(set checker-version-command).[/yellow]"
            )
            return None
        cache = ResultCache(db, self.root)
        reason = cache.validate(meta)
        if reason is not None:
            self.console.print(f"Result cache reset: {reason}.")
        return cache

    def _reuse(
        self, db: Database, cache: ResultCache, mutants: Iterable[MutantRow]
    ) -> Collection[MutantRow]:
        """Store the cached kills that are still valid in *db*; the mutants left to run."""
        found = cache.reuse(mutants)
        db.update_results_batch(found.reused)
        self.console.print(f"Reused {len(found.reused)} cached kills.")
        if found.stale + found.untraceable > 0:
            self.console.print(
                f"Rerunning {found.stale} kills whose files changed and "
                f"{found.untraceable} kills the checker output did not trace to files."
            )
        return found.remaining

    def _describe(self, checker: TypeChecker) -> str:
        """The checker's name with the config files it found and the cache it would use."""
        details = [
            f"{label}: {', '.join(os.path.relpath(path, self.root) for path in paths)}"
            for label, paths in (
                ("config", list(checker.config_files(self.root))),
                ("cache", list(checker.cache_paths(self.root))),
            )
            if paths
        ]
        return f"{checker.name} ({'; '.join(details)})" if details else checker.name

    def _executor(self, tester: MutationTester, checker: TypeChecker, jobs: int) -> MutantExecutor:
        """Runs mutants in the project, or with *jobs* > 1 in worktrees given *checker*'s cache."""
        if jobs > 1:
            workspace = GitWorkspace(
                self.root, self.runner, checker.worktree_cache_paths(self.root)
            )
            return WorktreeExecutor(tester, workspace, self.worker_pool, jobs)
        return SequentialExecutor(tester, self.root)

    def _find_mutants(
        self,
        files: Iterable[Path],
        cfg: Config,
        finder: MutationFinder,
    ) -> Collection[MutantRow]:
        """All mutations of the annotations in *files*, as pending database rows."""
        annotations = AnnotationFinder(cfg.skip_comments)
        mutants: list[MutantRow] = []
        for py_file in files:
            for ann in annotations.find(py_file):
                mutants.extend(
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
                    for mutation in finder.find(ann)
                )
        return mutants
