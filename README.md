# typemut

Mutation testing for Python type annotations.

Standard mutation testing tools (cosmic-ray, mutmut) mutate runtime code and check if tests catch it. **typemut** mutates only type annotations and checks if type checkers (mypy, pyright) catch the change.

- **Mutant killed** = type checker reports an error (types are strict enough)
- **Mutant survived** = no type error (types are too loose or type checker coverage is weak)

**Documentation: <https://nkhitrov.github.io/typemut/>**

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
```

All [operators](https://nkhitrov.github.io/typemut/operators/) are enabled by default; see the
[configuration reference](https://nkhitrov.github.io/typemut/configuration/) for every key.

2. Run:

```bash
typemut run                          # full pipeline: discover + execute + report
typemut html --open                  # generate HTML report and open in browser
typemut -C /path/to/project run      # or from another directory
```

3. On a real project, run mutants on several workers (needs a clean git working
   tree, see [Parallel runs](https://nkhitrov.github.io/typemut/parallel/)):

```bash
typemut run --jobs 8
```

## Features

- **[8 operators](https://nkhitrov.github.io/typemut/operators/)** — remove union/literal members, add or remove
  `Optional`, widen types and containers, swap `Iterator`/`Generator`, change
  `TypeVar` variance.
- **[Type checkers](https://nkhitrov.github.io/typemut/type-checkers/)** — mypy, pyright, basedpyright, a generic
  fallback and third-party checker plugins; mutants that break the code are
  reported as `error`, not as kills.
- **[Parallel runs](https://nkhitrov.github.io/typemut/parallel/)** — `--jobs N` runs mutants in N git worktrees.
- **[CI gating](https://nkhitrov.github.io/typemut/ci/)** — `--fail-under` and a baseline of accepted survivors.
- **[Incremental runs](https://nkhitrov.github.io/typemut/incremental/)** — `--incremental` reuses kills whose
  files are unchanged, with recipes to [keep the database between CI runs](https://nkhitrov.github.io/typemut/ci-database/)
  on GitHub Actions and GitLab CI.
- **[Plugins](https://nkhitrov.github.io/typemut/plugins/)** — SQLAlchemy, FastAPI, framework entrypoints and
  third-party plugins.
- **[Filtering](https://nkhitrov.github.io/typemut/filtering/)** — skip comments, excluded modules, ignored types
  and class hierarchies per operator.
- **[HTML report](https://nkhitrov.github.io/typemut/html-report/)** with per-mutant diffs and checker output.
- **[CLI reference](https://nkhitrov.github.io/typemut/commands/)** — `run`, `init`, `exec`, `report`, `html`.

## Contributing

See [Contributing](https://nkhitrov.github.io/typemut/contributing/).
