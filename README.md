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

## Commands

| Command | Description |
|---------|-------------|
| `typemut run` | Full pipeline: discover mutations, run type checker, show report |
| `typemut init` | Discover mutations and store in SQLite |
| `typemut exec` | Run type checker against each pending mutation |
| `typemut report` | Show terminal report |
| `typemut html` | Generate HTML report with diffs |

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

Mutation testing is slow, so use `--jobs N` in CI (it needs a clean git working tree).
typemut runs this on itself — see `make mutate` and `.github/workflows/ci.yml`.

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
