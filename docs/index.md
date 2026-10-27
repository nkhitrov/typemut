# typemut

Mutation testing for Python type annotations.

Standard mutation testing tools (cosmic-ray, mutmut) mutate runtime code and check
if tests catch it. **typemut** mutates only type annotations and checks if type
checkers (mypy, pyright) catch the change.

- **Mutant killed** = type checker reports an error (types are strict enough)
- **Mutant survived** = no type error (types are too loose or type checker coverage is weak)
- **Mutant error** = the mutant broke the code itself (e.g. an undefined name), excluded from the mutation score

```python
# Original
def greet(name: str | None) -> str: ...

# Mutant: remove None — survives if no caller ever passes None
def greet(name: str) -> str: ...
```

## Features

- **[8 operators](operators.md)** — remove union/literal members, add or remove `Optional`,
  widen types to their bases and containers to abstract ones, swap `Iterator`/`Generator`,
  change `TypeVar` variance.
- **[Type checkers](type-checkers.md)** — mypy, pyright, basedpyright, any other command
  via the generic checker, and third-party checker plugins. False kills from broken
  mutants are reported as `error`.
- **[Parallel runs](parallel.md)** — `--jobs N` runs mutants in N git worktrees.
- **[CI gating](ci.md)** — `--fail-under` and a baseline of accepted survivors.
- **[GitHub Action](ci-database.md)** — `uses: nkhitrov/typemut@<release>` runs typemut
  incrementally and keeps the database of the default branch as an artifact.
- **[Incremental runs](incremental.md)** — reuse kills whose files are unchanged; recipes to
  [keep the database between CI runs](ci-database.md) on GitHub Actions and GitLab CI.
- **[Plugins](plugins.md)** — SQLAlchemy, FastAPI, FastStream, django-modern-rest, pydantic and taskiq, framework
  entrypoints, third-party plugins.
- **[Filtering](filtering.md)** — skip comments, excluded modules, `@override` signatures, ignored types
  and class hierarchies.
- **[HTML report](html-report.md)** with per-mutant diffs and checker output.

Start with [Getting started](getting-started.md).
