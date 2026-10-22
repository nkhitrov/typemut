# Getting started

## Installation

```bash
pip install typemut
# or
uv add typemut
```

## Quick start

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

3. On a real project, run mutants on several workers — see
   [Parallel runs](parallel.md):

```bash
typemut run --jobs 8                 # needs a clean git working tree
```

## Next steps

- [Operators](operators.md) — what typemut mutates.
- [Using in CI](ci.md) — fail the build on new survivors with a baseline.
- [Incremental runs](incremental.md) — reuse kills of earlier runs to keep CI fast.
- [Configuration](configuration.md) — every `typemut.toml` key.
