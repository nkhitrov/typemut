.PHONY: install test lint lint-all fmt clean run

PYTHON_VERSIONS ?= 3.11 3.12 3.13

install:
	uv sync --all-extras --all-groups

test:
	uv run pytest tests/ -v

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
