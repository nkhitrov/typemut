# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

typemut — mutation testing tool for Python type annotations. It mutates annotations (never runtime code), runs the configured type checker (`test-command`) for each mutant, and records killed (checker failed) / survived (checker passed) / error (mutant broke the code) in SQLite.

## Commands

- `make install` — install dependencies (`uv sync --all-extras --all-groups`)
- `make test` — run tests with coverage
- `uv run pytest tests/test_engine.py::test_name -v` — run a single test
- `make lint` — run all linters (ruff, flake8/wps, mypy) on `src/typemut/`
- `make lint-all` — run linters + tests on Python 3.11, 3.12, 3.13
- `make fmt` — auto-format code (ruff)
- `make mutate` — run typemut on its own sources (`typemut.toml`, `mypy src/typemut/`, `--jobs 4`) and fail on survivors missing from `typemut-baseline.json`; CI runs this too
- `make run PROJECT=/path/to/project` — run typemut against another project (also `init`/`exec`/`report`/`html` targets)

Pre-commit hooks (lefthook) run ruff, flake8 and mypy on staged files. Coverage has per-module minimums in `pyproject.toml` (`[tool.coverage-threshold]`), e.g. `config.py` must stay at 100%.

## Architecture

Pipeline (`app.App`, driven by click commands in `cli.py`): `init` = discover → store; `exec` = run pending mutants; `report`/`html` read the DB; `run` does all of it.

- **Discovery** (`discovery.py`): `SourceFiles` lists `.py` files under `module-path`; `AnnotationFinder` walks the parso tree and yields `AnnotationNode`s (params, returns, annassigns, `TypeVar(...)` calls), skipping lines with skip-comments and bare `Any`.
- **Mutations**: `plugins.MutationFinder` gives each annotation to enabled plugins first (a plugin can claim it and decide its mutations), otherwise to every enabled operator from `operators.OperatorRegistry`. `ignore.IgnoredTypes` filters per-operator ignored types by the qualified import name. `registry.RegistryBuilder` builds a project-wide class hierarchy (used by `WidenType`) and import lines to inject.
- **Operators** (`operators/`) subclass `TypeMutationOperator` and return `Mutation`s (original text, mutated text, line/col, optional `required_import`). Mutants are stored as text replacements, not trees.
- **Execution** (`engine.py`): `MutationTester.run` applies a mutant via `MutationApplier` (exact source-offset replacement + import injection), runs the test command, restores the file. Mutated files get a content-derived mtime so mypy's incremental cache isn't fooled. `OutcomeClassifier` treats failures whose mypy codes are only `name-defined`/`syntax`/`valid-type` as `error`, not `killed`. `ResultRecorder` flushes results to the DB in batches, so an interrupted `exec` resumes the remaining `pending` mutants.
- **Parallelism** (`parallel.py`): with `--jobs N > 1`, `WorktreeExecutor` requires a clean git tree, creates N detached `git worktree`s in temp dirs, splits mutants by file (`FileGroupPartitioner`) and runs each chunk in its own process (`ProcessPool`). The baseline check always runs in the project root, not in worktrees.
- **Gating** (`baseline.py`, `App.check_results`): `--fail-under` and `--baseline` (survivors matched by file, operator, annotations and source-line text, not line number).
- **Plugins** (`plugins/`): built-in `sqlalchemy`, `fastapi`; third-party ones via the `typemut.plugins` entry point group.
- Errors meant for the user are `errors.TypemutError(message, details)`; the click group prints them and exits 1.

## Rules

- Before pushing a branch or creating a PR, always run `make lint-all` locally and ensure it passes on all Python versions.
- Do not push or create a PR if linters or tests fail.
- All imports in test files must be at the top of the file, not inside test functions.
- Tests must only cover public functions and classes. Do not test private functions (prefixed with `_`).
- Do not use `mock.patch` or `monkeypatch` to stub internal functions. Cover code paths by choosing appropriate input values instead.
- Logic lives in classes whose collaborators come in through the constructor, with the real implementation as the default. Module-level functions are only for click commands in `cli.py`; helpers are `_methods` of the class that uses them (shared parso helpers sit in base classes: `NodeSource`, `TypeMutationOperator`, `Plugin`), so plugins and subclasses can override them. No behaviourless "services" bags: dependencies are fields of the class that uses them (e.g. `App`).
- Side effects go through injectable seams: `CommandRunner` (`typemut.runner`), `MutantExecutor`/`ProgressBar` (`typemut.engine`), `GitWorkspace`/`WorkerPool` (`typemut.parallel`), `OperatorRegistry`, `PluginRegistry`, `SourceReader` (`typemut.reporting.html`). In tests use the stubs in `tests/fakes.py`; for CLI tests pass an app factory via `CliRunner().invoke(main, args, obj=partial(App, runner=..., ...))`. New side effects need a seam, not a patch.
- No `# pragma: no cover`: unreachable code is removed, reachable code is tested.
- Do not use `if`, `match/case`, or other conditional logic in test bodies. Tests must have deterministic, straight-line assertions.
- Do not use `parso` directly in tests. Test only through the library's public interface (source strings as input, mutation results as output).
- New survivors from `make mutate`: fix the annotation or the operator; don't grow `typemut-baseline.json` to hide them. Use `# pragma: no mutate` only for genuinely equivalent mutants.
- When adding a CLI option, operator or config key, update the README (Commands / Config Reference sections).
