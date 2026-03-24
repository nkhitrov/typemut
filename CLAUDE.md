# CLAUDE.md

## Project

typemut — mutation testing tool for Python type annotations.

## Commands

- `make install` — install dependencies
- `make test` — run tests
- `make lint` — run all linters (ruff, flake8/wps, mypy)
- `make lint-all` — run linters + tests on Python 3.11, 3.12, 3.13
- `make fmt` — auto-format code (ruff)

## Rules

- Before pushing a branch or creating a PR, always run `make lint-all` locally and ensure it passes on all Python versions.
- Do not push or create a PR if linters or tests fail.
- All imports in test files must be at the top of the file, not inside test functions.
