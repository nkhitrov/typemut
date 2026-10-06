.PHONY: install test lint lint-all fmt clean run mutate mutate-baseline

PYTHON_VERSIONS ?= 3.11 3.12 3.13

install:
	uv sync --all-extras --all-groups

test:
	uv run pytest tests/ -v --cov=typemut --cov=tests --cov-report=term-missing

lint:
	uv run ruff check src/typemut/
	uv run ruff format --check src/typemut/
	uv run flake8 src/typemut/
	uv run mypy src/typemut/

lint-all:
	@for pyv in $(PYTHON_VERSIONS); do \
		echo "=== Python $$pyv ==="; \
		uv run --python $$pyv --all-extras ruff check src/typemut/ && \
		uv run --python $$pyv --all-extras ruff format --check src/typemut/ && \
		uv run --python $$pyv --all-extras flake8 src/typemut/ && \
		uv run --python $$pyv --all-extras mypy src/typemut/ && \
		uv run --python $$pyv --all-extras pytest tests/ -v || exit 1; \
	done

fmt:
	uv run ruff check --fix src/typemut/
	uv run ruff format src/typemut/

# Mutation-test typemut's own annotations; fails on any survived mutant
# that is not in the baseline. `make mutate-baseline` accepts the current ones.
# Kills of earlier runs in typemut.sqlite are reused while their files are
# unchanged (--incremental); extra options go in MUTATE_ARGS, e.g.
#   make mutate MUTATE_ARGS="--refresh --max-duration 1500"
JOBS ?= 4
BASELINE ?= typemut-baseline.json
MUTATE_ARGS ?=

mutate:
	uv run typemut run --jobs $(JOBS) --incremental --baseline $(BASELINE) $(MUTATE_ARGS)

mutate-baseline:
	uv run typemut run --jobs $(JOBS) --baseline $(BASELINE) --update-baseline

clean:
	rm -f typemut.sqlite
	rm -rf .pytest_cache __pycache__ src/typemut/__pycache__
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# Run typemut on an external project:
#   make run PROJECT=/path/to/project
#   make run PROJECT=/path/to/project CONFIG=custom.toml
PROJECT ?= .
CONFIG ?= typemut.toml
DB ?= typemut.sqlite

run:
	uv run typemut -C $(PROJECT) run --config $(CONFIG) --db $(DB)

init:
	uv run typemut -C $(PROJECT) init --config $(CONFIG) --db $(DB)

exec:
	uv run typemut -C $(PROJECT) exec --config $(CONFIG) --db $(DB)

report:
	uv run typemut -C $(PROJECT) report --db $(DB)

html:
	uv run typemut -C $(PROJECT) html --db $(DB)
