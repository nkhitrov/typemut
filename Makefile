.PHONY: install test lint fmt clean run

install:
	uv sync --all-extras --all-groups

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/typemut/
	uv run ruff format --check src/typemut/
	uv run flake8 src/typemut/
	uv run mypy src/typemut/

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
