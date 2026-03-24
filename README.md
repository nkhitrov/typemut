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
swap-literal-value = true
widen-type = true
strip-annotated = true
remove-optional = true
add-optional = true
swap-container-type = true
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

### SwapLiteralValue

Swaps values inside `Literal[...]` with other literal values from the same file.

```python
# Original
status: Literal["active"]

# Mutant (if "closed" exists in the same file)
status: Literal["closed"]
```

**Survived = literal values are interchangeable from the type checker's perspective.** The code doesn't use literal narrowing or overloads to distinguish between the values.

### StripAnnotated

Removes metadata from `Annotated[X, ...]`, leaving just the base type.

```python
# Original
age: Annotated[int, Gt(0)]

# Mutant
age: int
```

**Survived = expected in most cases.** `Annotated` metadata is typically runtime-only (Pydantic validators, etc.). Survived mutants here are normal unless you use mypy plugins that understand the metadata.

### SwapContainerType

Swaps between compatible container types.

```python
# Original
items: list[int]

# Mutant
items: tuple[int]
```

**Swap groups:** `list` <-> `tuple`, `set` <-> `frozenset`. Dict has no swap target.

**Survived = code doesn't rely on container-specific behavior at the type level.** For example, if code only iterates over items, both `list` and `tuple` work equally.

## Filtering

Annotations are automatically skipped when:

- The line contains `# type: ignore` or `# pragma: no mutate`
- The annotation is `Any` (mutations are meaningless — Any absorbs all types)
- `AddOptional` targets a function parameter (low signal — callers won't pass None)

## Config Reference

```toml
[typemut]
module-path = "src/myproject"           # directory to scan for annotations
test-command = "make typecheck"         # command to run type checker
timeout = 30                            # seconds per mutation
excluded-modules = ["src/vendor/*.py"]  # glob patterns to skip
skip-comments = ["type: ignore", "pragma: no mutate"]
db = "typemut.sqlite"                   # database file

[typemut.operators]
# all enabled by default, disable selectively
remove-union-member = true
swap-literal-value = true
widen-type = true
strip-annotated = true
remove-optional = true
add-optional = true
swap-container-type = true
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
make lint       # run mypy
```

## Dependencies

- **parso** — CST parsing (preserves formatting and whitespace)
- **rich** — terminal reporting
- **click** — CLI framework
