# typemut

Mutation testing for Python type annotations.

Standard mutation testing tools (cosmic-ray, mutmut) mutate runtime code and check if tests catch it. **typemut** mutates only type annotations and checks if type checkers (mypy, pyright) catch the change.

- **Mutant killed** = type checker reports an error (types are strict enough)
- **Mutant survived** = no type error (types are too loose or type checker coverage is weak)

## Installation

```bash
pip install typemut
# or
uv add typemut
```

## Quick Start

1. Create `typemut.toml` in your project root:

```toml
[typemut]
module-path = "src/myproject"
test-command = "make typecheck"  # must exit non-zero on type errors
checker = "mypy"  # or pyright/basedpyright; needed when test-command is a wrapper like make
timeout = 30

[typemut.operators]
remove-union-member = true
remove-literal-member = true
widen-type = true
remove-optional = true
add-optional = true
widen-container-type = true
swap-iterator-generator = true
typevar-variance = true
```

2. Run:

```bash
typemut run                          # full pipeline: discover + execute + report
typemut html --open                  # generate HTML report and open in browser
```

Or from another directory:

```bash
typemut -C /path/to/project run
```

3. Run on several workers. Each mutant is a full type checker run, so a single
   worker is slow on a real project. `--jobs N` runs mutants on N workers in parallel:

```bash
git status --porcelain               # must print nothing: workers only see committed code
typemut run --jobs 8                 # 8 type checker processes at once
```

With `--jobs` greater than 1, typemut creates N temporary `git worktree`s of the
current commit, splits the mutants between them (all mutants of one file go to
the same worker), runs each worker in its own process and removes the worktrees
at the end. What this means for your project:

- **The working tree must be clean.** Uncommitted or untracked files would not
  be in the worktrees, so typemut refuses to start and lists them. Commit or
  stash them first.
- **`test-command` runs inside each worktree**, not in your project directory.
  Keep `module-path` and paths in `test-command` relative to the project root.
  Git-ignored files (`.venv`, generated code) are not copied: the type checker
  must be callable without them — e.g. installed in an activated virtualenv or
  on `PATH`.
- **The type checker's cache is copied into each worktree**, so workers start
  warm: the baseline check fills it in the project first, then every new
  worktree gets a copy with modification times and symlinks kept (mypy drops
  cache entries whose times differ). For mypy that is the directory shown as
  `cache:` in the `Type checker:` line (see [Type checkers](#type-checkers));
  a cache outside the project is not used. pyright and `generic` have no cache
  to copy. A missing cache is skipped and a failed copy is logged as a warning;
  that worker then starts cold.
- **Pick N by CPU cores and memory**: every worker runs its own type checker
  process (mypy on a large project can take gigabytes of RAM). The number of
  CPU cores is a good start.
- The baseline check (type checker on unmodified code) runs once, in the
  project itself, before the workers start.

`--jobs` is also available on `typemut exec`. Without it (or with `--jobs 1`)
mutants run one by one directly in your project, which needs neither git nor a
clean tree.

## Commands

Global option: `-C, --project-dir PATH` — change to this directory before running
(the target project's root, where `typemut.toml` lives).

| Command | Description |
|---------|-------------|
| `typemut run` | Full pipeline: discover mutations, run the type checker on each, show the report |
| `typemut init` | Discover mutations and store them in SQLite (replaces previous results; the [result cache](#fast-ci-incremental-runs) keeps the kills of incremental runs) |
| `typemut exec` | Run the type checker against each **pending** mutation |
| `typemut report` | Show the terminal report |
| `typemut html` | Generate the HTML report with diffs |

`init` + `exec` + `report` are the steps of `run`. Running them separately lets
you resume: results are saved as they arrive, so after an interrupted `exec`
(Ctrl+C, CI timeout) run `typemut exec` again and it continues with the
mutants that are still pending.

### `typemut run`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |
| `--jobs N` | `1` | Number of parallel workers (see [Quick Start](#quick-start)) |
| `--incremental / --no-incremental` | `incremental` from config (off) | Reuse kills of earlier runs whose files are unchanged (see [Fast CI](#fast-ci-incremental-runs)) |
| `--refresh` | — | Run every mutant without reusing anything, and store the results for later incremental runs |
| `--max-duration SECONDS` | `max-duration` from config (none) | Start no new mutant after this many seconds; finished results are saved |
| `--fail-under PERCENT` | — | Exit with code 1 if the mutation score is below this value |
| `--baseline PATH` | — | JSON file of accepted survivors; exit with code 1 on any other survivor |
| `--update-baseline` | — | Write the current survivors to the `--baseline` file instead of checking it |

### `typemut init`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |

### `typemut exec`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |
| `--jobs N` | `1` | Number of parallel workers |
| `--incremental / --no-incremental` | `incremental` from config (off) | Reuse kills of earlier runs whose files are unchanged |
| `--refresh` | — | Run the pending mutants without reusing cached kills, and store the results for later incremental runs (`exec` only runs pending mutants: use `run --refresh`, or `init` first, to recheck every mutant) |
| `--max-duration SECONDS` | `max-duration` from config (none) | Start no new mutant after this many seconds |

### `typemut report`

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `typemut.sqlite` | Database file |
| `--fail-under PERCENT` | — | Exit with code 1 if the mutation score is below this value |
| `--baseline PATH` | — | JSON file of accepted survivors; exit with code 1 on any other survivor |
| `--update-baseline` | — | Write the current survivors to the `--baseline` file instead of checking it |

### `typemut html`

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `typemut.sqlite` | Database file |
| `-o, --output PATH` | `typemut-report.html` | Output file |
| `--open` | — | Open the report in a browser |

## Using in CI

`typemut run` and `typemut report` exit with code 0 regardless of survivors unless
you ask them to gate:

```bash
typemut run --fail-under 90                          # exit 1 if the mutation score is below 90%
typemut run --baseline typemut-baseline.json         # exit 1 on survivors not in the baseline
typemut run --baseline typemut-baseline.json --update-baseline   # accept the current survivors
```

A **baseline** is a JSON file of survived mutants you have reviewed and accept
(e.g. equivalent mutants the type checker can never kill). Commit it and run with
`--baseline` in CI: known survivors pass, new ones fail the build and are listed.
Entries are matched by file, operator, original and mutated annotation, and the
text of the source line — not its number, so edits elsewhere in a file keep the
baseline valid. Entries that no longer survive are reported; rerun with
`--update-baseline` to drop them.

`run` and `report` also exit with code 1 while any mutant is still pending (a run
stopped by `--max-duration`, an interrupted `exec`), and then do not update the
baseline: a gate on incomplete results would pass by accident.

Mutation testing is slow, so use `--jobs N` in CI (it needs a clean git working tree,
see [Quick Start](#quick-start)), and `--incremental` (below).
typemut runs this on itself — see `make mutate` and `.github/workflows/ci.yml`.

## Fast CI: incremental runs

`typemut run --incremental` reuses the kills of earlier runs stored in the same
database, and runs only the mutants that are new, survived, ended in `error`,
or whose kill may no longer hold:

```bash
typemut run --incremental --jobs 4 --baseline typemut-baseline.json
```

**What is reused.** A killed mutant is identified by its file, line, column,
operator, original and mutated annotation and required import. When it is
killed, typemut records the files the kill depends on, with a hash of each: the
mutated file, the files the checker reported errors in, and every project file
those import (directly or not). The next incremental run copies the kill
(status and checker output) if all those files are unchanged, and prints
`Reused N cached kills`.

**What always runs again.** Survived and `error` mutants; kills by timeout;
kills whose errors are outside the project root (in installed packages) or
whose output names no file (a `test-command` that `cd`s before running the
checker); every mutant under the `generic` checker, which cannot tell the
files a kill depends on (the run says so, and stores nothing in the cache); kills whose files changed (the run prints
how many). The baseline check always runs too: it catches a broken tree and
warms the checker's cache.

**When the whole cache is dropped.** The cache is reset, with the changed input
named (`Result cache reset: checker version changed.`), when any of these differ
from the run that filled it: the typemut version (and, for unreleased builds,
its sources), the checker and its version, the version of the Python it runs
with, `test-command`, `timeout`, the checker's config files (`mypy.ini`,
`pyproject.toml`, `pyrightconfig.json`, ...) and the files matched by
`cache-key-files` (by default the lockfiles `uv.lock`, `poetry.lock`,
`requirements*.txt`). Patterns in `cache-key-files` are relative to the
project root; absolute, empty and invalid ones are skipped with a warning. If the checker's
version is unknown (see [Type checkers](#type-checkers); set
`checker-version-command`), that run neither reuses nor stores results and
leaves the cache as it is, so a single failed version check does not discard
it: the next run with a known version reuses the kills again. The Python version is that of
`python --version`, run through the project runner the checker runs with
(`uv run python --version` for `uv run mypy`, `python3.12 --version` for
`python3.12 -m mypy`) or from the directory of a checker run by path
(`.venv/bin/python --version` for `.venv/bin/mypy`).

**Keeping the cache fresh.** `typemut run --refresh` runs every mutant and
stores the results without reusing any: run it on a schedule (e.g. weekly) to
recheck the kills. (`exec --refresh` only runs the mutants still pending.) Without `--incremental` nothing is reused or stored, and the kills
already in the result cache stay there: a run without the flag (or `init`)
between two incremental runs does not discard them.

**Time limits.** `--max-duration SECONDS` (or `max-duration` in the config)
stops starting new mutants after that many seconds, waits for the running
ones and saves every finished result; the run then fails with
`N mutants not run yet`. Keep it below the CI job timeout. A run
stopped by `SIGTERM` (as CI runners stop jobs) saves its finished results too.
On a project with no cache yet, a first run may not fit in the CI timeout:
store the database after every run on the main branch (even a failed one), and
each next incremental run continues from the kills of the previous ones until
the whole project is covered.

The cache lives in the database file (`typemut.sqlite` by default): keep it
out of git (it is binary and changes on every run; with `--jobs` an untracked
file in the project fails the clean-tree check, so list it in `.gitignore` or
pass `--db` outside the project) and carry it between CI runs as a build
artifact or cache.

**Limits.** Reuse trusts the checker's output and typemut's import graph. For
every imported project module both its `.py` file and its `.pyi` stub are
tracked, so adding a stub next to a module (or a module next to a stub)
reruns the kills that depend on it. A file the checker reads that is not
imported (a plugin config, a stub found through `mypy_path` outside the
project, a new module that shadows another on the search path) is not
tracked; list it in
`cache-key-files` if a change to it can turn a kill into a survivor. For a
checker run by name without a project runner (`mypy src`, `npx pyright`), the
Python version is that of the `python` on `PATH`, which may not be the one the
checker runs with (a pipx-installed mypy), or may be missing (systems with only
`python3`): then a Python upgrade does not reset the cache; run the checker
through its environment (`uv run mypy`, `.venv/bin/mypy`) or use `--refresh`.

## Type checkers

typemut runs `test-command` as is, but it reads the output with a plugin for the
type checker that command runs. The plugin tells a real kill from a mutant that
merely broke the code: a failure whose only errors are a missing name, a syntax
error or an invalid type is recorded as `error`, not `killed`. It also finds the
checker's config files and cache directory. The checker's version, the files
with errors and which project files a file imports are known to the plugin
too: [incremental runs](#fast-ci-incremental-runs) use them to tell whether
an earlier kill can be reused.

| `checker` | Recognised executables | Errors counted as broken code |
|-----------|------------------------|-------------------------------|
| `mypy` | `mypy`, `dmypy` | `[name-defined]`, `[syntax]`, `[valid-type]` |
| `pyright` | `pyright` | `reportUndefinedVariable`, `reportInvalidTypeForm`, errors without a rule (syntax errors) |
| `basedpyright` | `basedpyright` | same as `pyright` (a subclass: the output format is the same) |
| `generic` | — | mypy-style `[code]` at the end of any output line, as above |

By default (`checker = "auto"`) the checker is detected from `test-command`:
a recognised executable counts when it is the command itself, possibly after
environment assignments, `env`/`exec`/`time`, or a runner (`uv run`,
`poetry run`, `pipx run`, `pdm run`, `hatch run`, `rye run`, `pnpm exec`,
`uvx`, `npx`, `bunx`, `python -m`), in any command of a chain
(`uv run mypy src`, `python -m mypy -p app`, `cd src && npx pyright`).
Runner options are skipped, with their values (`uv run --group dev mypy`,
`npx -p pyright pyright`). An
executable name passed to another tool (`tox -e mypy`,
`pre-commit run mypy --all-files`) is not detected. A command that runs none
of them (`make typecheck`, a script, a wrapper like `tox`), or more than one
(`mypy src && pyright src`), gets the `generic` checker and a warning; name the
checker instead:

```toml
[typemut]
test-command = "make typecheck"
checker = "mypy"
```

The run prints the checker it uses, with the config files it found and the
cache directory it would use (and copy into each worktree with `--jobs`),
relative to the project root
(`Type checker: mypy (config: pyproject.toml; cache: .mypy_cache)`); the cache
is listed even before mypy has created it. mypy's cache directory comes from
`--cache-dir`, `MYPY_CACHE_DIR`, `cache_dir` in its config, or `.mypy_cache`,
with `~` and `$VAR` expanded as mypy does.
An unknown `checker` name is logged as a warning and `generic` is used. mypy's
`--pretty`, `--show-column-numbers` and `--show-error-end` output is understood;
only errors count (mypy notes, pyright warnings and information are ignored).
Both stdout and stderr are parsed, so noise from wrappers such as `uv run` on
stderr does not hide the checker's errors.

Incremental runs reuse earlier kills only while the checker's version is the
same, and do not use the cache at all while it is unknown. It is taken from `test-command` up to the checker executable plus `--version`,
as written there (`cd backend && uv run mypy .` -> `cd backend && uv run mypy --version`:
of the commands before the checker only `cd` and `pushd` are kept). If the
command does not run the executable directly (`tox -e mypy`, `make typecheck`),
set `checker-version-command`, e.g. `checker-version-command = "npx pyright --version"`;
the first `X.Y.Z` in its output is the version. `generic` only has a version
when `checker-version-command` is set, but it never reuses kills anyway: it
cannot tell which files they depend on.

### Third-party checkers

A package can ship a checker plugin: subclass `typemut.checkers.base.TypeChecker`
and register it under the `typemut.checkers` entry point group. The entry point
name is the value for `checker = ...`:

```toml
# pyproject.toml of the plugin package
[project.entry-points."typemut.checkers"]
pytype = "typemut_pytype:PytypeChecker"
```

```python
from collections.abc import Iterable

from typemut.checkers.base import Diagnostic, TypeChecker


class PytypeChecker(TypeChecker):
    name = "pytype"
    executables = frozenset({"pytype"})

    def parse_output(self, output: str) -> Iterable[Diagnostic]:
        ...  # one Diagnostic(path, code) per error
```

Set `name`, `executables` (used for detection and the version command),
`false_kill_codes` and `config_names` (config files the checker reads from the
project root), and override `parse_output(output)` to return a
`Diagnostic(path, code)` (from `typemut.checkers.base`) for every error in one
output stream. `executables` should not overlap those of another checker:
`checker = "auto"` falls back to `generic` when a command matches two
unrelated checkers. The one exception is a subclass of a checker that shares
its executables (e.g. `class StrictMypyChecker(MypyChecker)` with the
inherited `mypy`): auto-detection then picks the subclass instead of its base.
Two such subclasses of the same checker installed together match both, so set
`checker = "<name>"` explicitly. `config_files`,
`cache_paths` (directories inside the project copied into each worktree),
`python_version` and `dependencies` (by default: the project
files reachable through imports; `None` means that kill is not reused) can be
overridden too. A checker that can never tell which files a kill depends on
(e.g. its output carries no file paths) should set
`traces_dependencies = False`: incremental runs then neither reuse nor store
its results and leave the cache alone, as with `generic`. The constructor takes
`(test_command, version_command, runner, graph=None, environ=None)`; *environ*
is the environment the checker runs with (the process environment by default). An entry point that fails to import
or does not name a `TypeChecker` subclass is logged as a warning and skipped.

## What It Finds

typemut generates mutations of type annotations and checks whether the type checker catches them. Each mutation operator targets a specific class of type safety issues.

### RemoveUnionMember

Removes one member from a union type.

```python
# Original
def handle(value: int | str | float) -> None: ...

# Mutant: remove str
def handle(value: int | float) -> None: ...
```

**Survived = your code doesn't distinguish between union members.** If removing `str` from the union causes no type error, it means no code path relies on `value` being a `str`. The union may be overly broad, or the type checker doesn't see the code that handles `str` specifically.

### RemoveOptional

Removes `None` from `X | None`.

```python
# Original
def find_user(id: int) -> User | None: ...

# Mutant
def find_user(id: int) -> User: ...
```

**Survived = callers don't check for `None`.** The return type says "might be None" but no consumer's type annotations actually require a None-check. Either the None case is dead code, or callers use `# type: ignore`.

### AddOptional

Adds `| None` to return types and class fields (parameters are excluded — callers simply won't pass None, making those mutations uninformative).

```python
# Original
class Config:
    name: str

# Mutant
class Config:
    name: str | None
```

**Survived = consumers don't rely on non-None guarantee.** The field claims to always have a value, but no typed code would break if it could be `None`. This often reveals missing type coverage in code that reads the field.

### WidenType

Replaces a concrete class with its parent (base) class to find places where a more abstract type could be used.

```python
class Animal: ...
class Cat(Animal): ...
class Dog(Animal): ...

# Original
def feed(pet: Cat) -> None: ...

# Mutant
def feed(pet: Animal) -> None: ...
```

**Survived = the code doesn't rely on the concrete subclass.** The function could accept the broader base type, suggesting the annotation is more specific than necessary.

### RemoveLiteralMember

Removes one value from a multi-value `Literal[...]`.

```python
# Original
def open_file(mode: Literal["r", "w", "a"]) -> None: ...

# Mutant: remove "a"
def open_file(mode: Literal["r", "w"]) -> None: ...
```

**Survived = that literal value is never used.** No typed caller passes `"a"`, so the Literal is broader than the code actually needs.

### WidenContainerType

Replaces a concrete container with the next more abstract type.

```python
# Original
def total(items: list[int]) -> int: ...

# Mutant
def total(items: Sequence[int]) -> int: ...
```

**Widening steps:** `list`/`tuple` → `Sequence`, `set`/`frozenset` → `AbstractSet`, `dict` → `Mapping`, `Sequence`/`AbstractSet`/`Mapping` → `Collection`, `Collection` → `Iterable`. `tuple[X, ...]` becomes `Sequence[X]`, `Mapping[K, V]` becomes `Collection[K]`, and heterogeneous tuples like `tuple[int, str]` are skipped.

**Survived = the code only uses the abstract interface.** A parameter could accept the wider type; a return type could promise less.

### SwapIteratorGenerator

Widens iterator/generator types by one step: `Iterator` → `Iterable`, `Generator[Y, S, R]` → `Iterator[Y]`, and the async equivalents.

```python
# Original
def read_lines(path: str) -> Generator[str, None, None]: ...

# Mutant
def read_lines(path: str) -> Iterator[str]: ...
```

**Survived = nobody uses the extra capability.** Callers never call `next()` / `send()` or read the generator's return value, so the simpler type is enough.

### TypeVarVariance

Removes `covariant=True` / `contravariant=True` from a `TypeVar`, or adds either one to an invariant `TypeVar`.

```python
# Original
T_co = TypeVar("T_co", covariant=True)

# Mutant
T_co = TypeVar("T_co")
```

**Survived = variance is not relied on (removal), or the TypeVar could be declared variant (addition).**

## Plugins

Core operators know nothing about libraries. Some libraries wrap your types in
their own generics and read them at runtime, which changes what a mutation
means. Plugins teach typemut these rules. They are opt-in:

```toml
[typemut]
plugins = ["sqlalchemy", "fastapi"]
```

An unknown plugin name is logged as a warning and skipped. A plugin can claim an annotation and decide
its mutations (usually by running the core operators on a wrapped type and
dropping mutations that are invalid for the library), and can contribute its own
operators. Annotations no plugin claims are mutated as usual.

### Third-party plugins

A package can ship its own plugin: subclass `typemut.plugins.base.Plugin` and
register it under the `typemut.plugins` entry point group. The entry point name
is the name used in `plugins = [...]`:

```toml
# pyproject.toml of the plugin package
[project.entry-points."typemut.plugins"]
django = "typemut_django:DjangoPlugin"
```

An entry point that fails to import or does not name a `Plugin` subclass is
logged as a warning and skipped.

A plugin's `find_mutations` receives the enabled operators and the class
registry. The `Plugin` base class also provides parso helpers
(`_node_code`, `_trailer_target`) that a plugin can use or override. Operators
a plugin returns from `operators()` subclass `TypeMutationOperator`, which
provides `_node_code`, `_is_qualified_name`, `_union_members` and `_type_params`.

### sqlalchemy

For SQLAlchemy 2.0 declarative models (`Mapped[...]`, also `orm.Mapped[...]`).
SQLAlchemy derives the column type, nullability and relationship target from
the type inside `Mapped[...]`, so the plugin mutates that type instead of the
whole annotation:

| Annotation | Without plugin | With plugin |
|------------|----------------|-------------|
| `id: Mapped[int]` | `Mapped[int] \| None` (meaningless) | `Mapped[int \| None]` (nullable column) |
| `email: Mapped[str \| None]` | not mutated | `Mapped[str]` |
| `user: Mapped["UserDB"] = relationship()` | `Mapped["UserDB"] \| None` | `Mapped["UserDB \| None"]` |
| `profile: Mapped["ProfileDB \| None"] = relationship()` | `Mapped["ProfileDB \| None"] \| None` | `Mapped["ProfileDB"]` |
| `roles: Mapped[list[RoleDB]] = relationship()` | `Mapped[Sequence[RoleDB]]` | skipped |
| `payload: Mapped[dict[str, Any]]` | `Mapped[Mapping[str, Any]]` | skipped |
| `user: Mapped[UserDB] = relationship()` (`UserDB(BaseDB)`) | `Mapped[BaseDB]` | skipped |

Rules:

- Quoted forward references (`Mapped["UserDB | None"]`) are mutated inside the quotes.
- `WidenContainerType` skips the top-level type inside `Mapped[...]`: SQLAlchemy needs a
  concrete column type / collection class there (`list`, `set`), not an ABC. Nested
  containers (`Mapped[dict[str, list[int]]]`) are still widened.
- On relationship attributes (`= relationship(...)`):
  - `WidenType` is skipped: the target must be a mapped class, and widening usually points
    at the declarative base;
  - `AddOptional` is skipped for collections (`Mapped[list[X]]`): a collection
    relationship is an empty collection, never `None`.
- `WriteOnlyMapped[...]` and `DynamicMapped[...]` get no mutations: they are always
  relationship collections, and none of the core mutations is valid for them.

Nullability mismatches between `Mapped[X | None]` and `mapped_column(nullable=...)`
are a runtime/schema issue, not a typing one, so the plugin does not generate them.

### fastapi

FastAPI calls route handlers itself, and tests reach them over HTTP, so no Python
code calls them. The type checker has no caller to check a mutated signature
against: `-> RedirectResponse` → `-> RedirectResponse | None` always survives.
The plugin skips all parameter and return annotations of such functions:

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/login")
async def login(next: str | None = None) -> RedirectResponse:  # not mutated
    target: str | None = next  # still mutated
    ...
```

A function counts as an endpoint when it is decorated with
`@<receiver>.<method>(...)`, where `<method>` is a route method (`get`, `post`, `put`,
`patch`, `delete`, `head`, `options`, `trace`, `api_route`, `websocket`) or
`exception_handler`, `middleware`, `on_event`. The receiver has to be an instance
of `fastapi.FastAPI` / `fastapi.APIRouter`, or of a project class inheriting from
them (also across modules). The type is resolved statically from imports, not
from variable names:

- `app = FastAPI()`, `router: APIRouter = make_router()`, `def register(app: FastAPI)`;
- `app = FastAPI()` inside an app factory function;
- a receiver imported from another project module, including re-exports
  (`from app.api import router`, `from app import api` + `@api.router.get`).

Unresolvable receivers (a factory call without annotation, `self.router`, a star
import) are not treated as endpoints. The same goes for functions registered
without a decorator (`app.add_api_route(...)`) or used only through `Depends(...)`.
Mark those with `# pragma: no mutate`.

## Filtering

Annotations are automatically skipped when:

- The line contains `# type: ignore` or `# pragma: no mutate`
- The annotation is `Any` (mutations are meaningless — Any absorbs all types)
- `AddOptional` targets a function parameter (low signal — callers won't pass None)

### Ignoring library types per operator

By default every operator mutates every annotation, including library wrapper
types it knows nothing about (`Mapped[int]` → `Mapped[int] | None`). To silence
such noise, list the types an operator must not touch under
`[typemut.ignore-types]`, keyed by operator (same keys as `[typemut.operators]`):

```toml
[typemut.ignore-types]
all = ["django.db.models.*"]                        # every operator
add-optional = ["sqlalchemy.orm.Mapped"]
remove-optional = ["sqlalchemy.orm.Mapped"]
widen-container-type = ["sqlalchemy.orm.Mapped"]
widen-type = ["sqlalchemy.orm.DeclarativeBase"]
```

- An operator skips every annotation that references one of its ignored types
  (anywhere in it, e.g. `list[Mapped[int]]`); other operators still mutate it.
- An operator also drops mutations that would introduce an ignored type, e.g.
  `WidenType` widening a model to `DeclarativeBase`.
- Patterns are `fnmatch` globs matched against the qualified name the type is
  **imported under** in the file (`from sqlalchemy.orm import Mapped` →
  `sqlalchemy.orm.Mapped`), not where it is defined. Aliases (`import sqlalchemy.orm as orm`,
  `orm.Mapped`) and relative imports of your own packages are resolved.
- Names that aren't imported (builtins, classes defined in the same file) are never ignored.
- Plugins see annotations first and are not affected: with `plugins = ["sqlalchemy"]`,
  `Mapped[...]` is still mutated correctly (`Mapped[int]` → `Mapped[int | None]`).
- Unknown operator keys and invalid values are logged as warnings and skipped.

## Config Reference

```toml
[typemut]
module-path = "src/myproject"           # directory to scan for annotations
test-command = "make typecheck"         # command to run type checker
timeout = 30                            # seconds per mutation
excluded-modules = ["src/vendor/*.py"]  # glob patterns to skip
skip-comments = ["type: ignore", "pragma: no mutate"]
db = "typemut.sqlite"                   # database file
plugins = ["sqlalchemy"]                # library plugins, none by default
checker = "mypy"                        # mypy, pyright, basedpyright, generic; default "auto" detects it
                                        # from test-command (set it when test-command is a wrapper like make)
# checker-version-command = "mypy --version"  # optional; for incremental runs;
                                        # default: test-command up to the checker + --version
incremental = false                     # reuse kills of earlier runs (--incremental / --no-incremental)
# max-duration = 1500                   # seconds; start no new mutant after it (--max-duration)
cache-key-files = ["uv.lock", "poetry.lock", "requirements*.txt"]  # glob patterns relative to the
                                        # project root (absolute, empty or invalid ones are skipped with a warning);
                                        # a change to any drops every cached result

[typemut.operators]
# all enabled by default, disable selectively
remove-union-member = true
remove-literal-member = true
widen-type = true
remove-optional = true
add-optional = true
widen-container-type = true
swap-iterator-generator = true
typevar-variance = true

[typemut.ignore-types]
# qualified type patterns each operator must not touch; "all" applies to every operator
all = []
add-optional = ["sqlalchemy.orm.Mapped"]
```

## HTML Report

The HTML report shows:
- Summary stats and per-module mutation scores
- Each mutant as a collapsible card with unified diff
- Color-coded status: killed (green), survived (red), error (orange)
- Full type checker output per mutant
- Expand/Collapse All controls

```bash
typemut html --open                     # save and open in browser
typemut html -o report.html             # save to specific file
```

## Development

```bash
make install    # create venv and install with dev deps
make test       # run tests
make lint       # run ruff, flake8/wps, mypy
make mutate     # run typemut on itself; fails on survivors missing from typemut-baseline.json
make mutate-baseline  # accept the current survivors (review the diff before committing)
```

## Dependencies

- **parso** — CST parsing (preserves formatting and whitespace)
- **rich** — terminal reporting
- **click** — CLI framework
