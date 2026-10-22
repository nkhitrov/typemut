"""Tests for WidenType operator."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.operators.widen_type import WidenType
from typemut.registry import RegistryBuilder

from tests.conftest import assert_mutations

ANIMALS = "class Animal: ...\nclass Cat(Animal): ...\nclass Dog(Animal): ...\n"


def widened(root: Path, sources: dict[str, str], file: str) -> list[tuple[str, str, str | None]]:
    """(original, mutated, required import) of the WidenType mutations in *file*."""
    for path, source in sources.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(source)
    registry = RegistryBuilder().build(sorted(root.rglob("*.py"))).in_file(root / file)
    return [
        (mutation.original, mutation.mutated, mutation.required_import)
        for annotation in AnnotationFinder().find(root / file)
        for mutation in WidenType().find_mutations(annotation.node, annotation.context, registry)
    ]


def test_no_widen_for_unknown_class() -> None:
    assert_mutations("x: SomeUnknown\n", WidenType, expected=[])


@pytest.mark.parametrize(
    "annotation,expected",
    [
        pytest.param("Cat", [("Cat", "Animal", None)], id="bare"),
        pytest.param("list[Cat]", [("Cat", "Animal", None)], id="in-container"),
        pytest.param(
            "Cat | Dog", [("Cat", "Animal", None), ("Dog", "Animal", None)], id="in-union"
        ),
        pytest.param('"Cat"', [], id="string"),
        pytest.param("Cat.Inner", [], id="dotted-head"),
        pytest.param("models.Cat", [], id="dotted-attribute"),
        pytest.param("Literal[Cat.MEOW]", [], id="literal"),
        pytest.param("typing.Literal[Cat]", [], id="qualified-literal"),
        pytest.param("Annotated[int, Depends(Cat)]", [], id="call-argument"),
        pytest.param("Annotated[Cat, Depends(Dog)]", [("Cat", "Animal", None)], id="annotated"),
    ],
)
def test_widen_positions(tmp_path: Path, annotation: str, expected: list[tuple]) -> None:
    sources = {"models.py": f"{ANIMALS}x: {annotation}\n"}
    assert widened(tmp_path, sources, "models.py") == expected


@pytest.mark.parametrize(
    "base",
    ["object", "ABC", "Generic[T]", "Protocol", "Protocol[T]", "NamedTuple", "TypedDict"],
)
def test_no_widen_to_interfaceless_base(tmp_path: Path, base: str) -> None:
    """Regression test for #14: e.g. a Protocol base must not be a WidenType target."""
    source = (
        "from abc import ABC\n"
        "from typing import Generic, NamedTuple, Protocol, TypedDict, TypeVar\n"
        "T = TypeVar('T')\n"
        f"class Child({base}): ...\n"
        "x: Child\n"
    )
    assert widened(tmp_path, {"models.py": source}, "models.py") == []


def test_widen_imports_base_from_defining_module(tmp_path: Path) -> None:
    """Regression test for #36: the base defined next to the subclass gets imported."""
    sources = {
        "pkg/__init__.py": "",
        "pkg/models.py": ANIMALS,
        "pkg/service.py": "from pkg.models import Cat\n\ndef adopt() -> Cat:\n    return Cat()\n",
    }
    assert widened(tmp_path, sources, "pkg/service.py") == [
        ("Cat", "Animal", "from pkg.models import Animal"),
    ]


def test_same_named_classes_widen_to_their_own_base(tmp_path: Path) -> None:
    sources = {
        "extra_models.py": "class UserBase: ...\nclass UserInDB(UserBase): ...\nu: UserInDB\n",
        "security.py": "class User: ...\nclass UserInDB(User): ...\n",
    }
    assert widened(tmp_path, sources, "extra_models.py") == [("UserInDB", "UserBase", None)]


def test_no_widen_to_alias_base(tmp_path: Path) -> None:
    sources = {
        "state.py": (
            "from collections import UserDict\n"
            "from typing import TYPE_CHECKING, Any\n"
            "if TYPE_CHECKING:\n"
            "    _Base = UserDict[str, Any]\n"
            "else:\n"
            "    _Base = UserDict\n"
            "class TaskiqState(_Base): ...\n"
        ),
        "broker.py": "from state import TaskiqState\nstate: TaskiqState\n",
    }
    assert widened(tmp_path, sources, "broker.py") == []


@pytest.mark.parametrize(
    "annotation,expected",
    [
        pytest.param("Page[str]", [("Page[str]", "BaseModel", None)], id="generic-child"),
        pytest.param("Page", [("Page", "BaseModel", None)], id="bare-generic-child"),
        pytest.param("list[Page[int]]", [("Page[int]", "BaseModel", None)], id="nested"),
        pytest.param("Items[int]", [], id="subscripted-base"),
        pytest.param("Items", [("Items", "list", None)], id="bare-subscripted-base"),
    ],
)
def test_widen_generic_class(tmp_path: Path, annotation: str, expected: list[tuple]) -> None:
    source = (
        "from typing import Generic, TypeVar\n"
        "from pydantic import BaseModel\n"
        "T = TypeVar('T')\n"
        "class Page(BaseModel, Generic[T]): ...\n"
        "class Items(list[T]): ...\n"
        f"x: {annotation}\n"
    )
    assert widened(tmp_path, {"models.py": source}, "models.py") == expected


def test_widen_enum_outside_literal_only(tmp_path: Path) -> None:
    source = (
        "from enum import Enum\n"
        "from typing import Literal\n"
        "class QueueType(str, Enum):\n"
        "    CLASSIC = 'classic'\n"
        "def declare(kind: QueueType, classic: Literal[QueueType.CLASSIC]) -> None: ...\n"
    )
    assert widened(tmp_path, {"queue.py": source}, "queue.py") == [("QueueType", "str", None)]
