"""Tests for skipping the signatures of ``@override`` methods."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry

METHOD = "    def get(self, key: str | None) -> Value | None: ...\n"

METHOD_MUTATIONS = {
    ("RemoveOptional", "str | None", "str"),
    ("RemoveOptional", "Value | None", "Value"),
}


def mutations(tmp_path: Path, source: str, plugins: list[str] | None = None) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *source*, written to a module of *tmp_path*."""
    file = tmp_path / "backend.py"
    file.write_text(source)
    finder = MutationFinder(
        OperatorRegistry().enabled({}), Registry(), PluginRegistry().get(plugins or [])
    )
    return {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(file)
        for mutation in finder.find(annotation)
    }


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f"from typing import override\nclass Redis(Base):\n    @override\n{METHOD}",
            id="typing",
        ),
        pytest.param(
            f"from typing_extensions import override\nclass Redis(Base):\n    @override\n{METHOD}",
            id="typing-extensions",
        ),
        pytest.param(
            f"import typing\nclass Redis(Base):\n    @typing.override\n{METHOD}",
            id="qualified",
        ),
        pytest.param(
            f"import typing_extensions as te\nclass Redis(Base):\n    @te.override\n{METHOD}",
            id="module-alias",
        ),
        pytest.param(
            f"from typing import override as ov\nclass Redis(Base):\n    @ov\n{METHOD}",
            id="name-alias",
        ),
        pytest.param(
            "import sys\n"
            "if sys.version_info >= (3, 12):\n"
            "    from typing import override\n"
            "else:\n"
            "    from typing_extensions import override\n"
            f"class Redis(Base):\n    @cached\n    @override\n    async{METHOD[3:]}",
            id="version-guarded-async-among-decorators",
        ),
    ],
)
def test_override_signature_is_not_mutated(tmp_path: Path, source: str) -> None:
    assert mutations(tmp_path, source) == set()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(f"class Redis(Base):\n    @override\n{METHOD}", id="not-imported"),
        pytest.param(
            f"from mylib import override\nclass Redis(Base):\n    @override\n{METHOD}",
            id="other-module",
        ),
        pytest.param(
            f"from typing import override\nclass Redis(Base):\n    @override()\n{METHOD}",
            id="called",
        ),
        pytest.param(
            f"from typing import final\nclass Redis(Base):\n    @final\n{METHOD}",
            id="other-typing-decorator",
        ),
        pytest.param(f"class Base:\n{METHOD}", id="parent"),
    ],
)
def test_other_signatures_are_mutated(tmp_path: Path, source: str) -> None:
    assert mutations(tmp_path, source) == METHOD_MUTATIONS


def test_override_body_is_mutated(tmp_path: Path) -> None:
    source = (
        "from typing import override\n"
        "class Redis(Base):\n"
        "    @override\n"
        "    def get(self) -> Value | None:\n"
        "        cached: Value | None = None\n"
        "        return cached\n"
    )

    assert mutations(tmp_path, source) == {
        ("RemoveOptional", "Value | None", "Value"),
    }


def test_override_comes_before_plugins(tmp_path: Path) -> None:
    source = (
        "from typing import override\n"
        "from sqlalchemy.orm import Mapped\n"
        "class Repo(Base):\n"
        "    @override\n"
        "    def get(self, key: Mapped[int]) -> Mapped[int]: ...\n"
    )

    assert mutations(tmp_path, source, ["sqlalchemy"]) == set()
