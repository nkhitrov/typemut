"""Shared test fixtures and helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.db import Database
from typemut.discovery import AnnotationContext, discover_annotations
from typemut.operators.base import Mutation
from typemut.registry import Registry

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def tmp_db(tmp_path: Path):
    """Database fixture with automatic cleanup."""
    db = Database(tmp_path / "test.sqlite")
    yield db
    db.close()


def assert_mutations(
    source: str,
    operator_cls: type,
    *,
    expected: list[str],
    context: AnnotationContext = AnnotationContext.VARIABLE,
    registry: Registry | None = None,
    index: int = 0,
    annotation_filter: str | None = None,
) -> list[Mutation]:
    """Assert that an operator produces the expected mutations from source."""
    annotations = discover_annotations(Path("test.py"), source=source)
    if annotation_filter:
        annotations = [a for a in annotations if annotation_filter in a.code]

    op = operator_cls()
    mutations = op.find_mutations(
        annotations[index].node, context, registry or Registry()
    )

    actual = {m.mutated for m in mutations}
    assert actual == set(expected), f"Expected {set(expected)}, got {actual}"
    return mutations
