"""Tests for per-operator ignored class hierarchies ([typemut.ignore-classes])."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.config import OperatorsConfig
from typemut.db import Database
from typemut.discovery import AnnotationFinder
from typemut.hierarchy import ClassHierarchy, ClassHierarchyBuilder, ClassNames
from typemut.ignore import IgnoredClasses
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry

RESPONSE = "pydantic.BaseModel"


def finder(
    ignore: Mapping[str, list[str]],
    hierarchy: ClassHierarchy,
    plugins: list[str] | None = None,
) -> MutationFinder:
    operators = OperatorRegistry().enabled(OperatorsConfig())
    return MutationFinder(
        operators,
        Registry(),
        PluginRegistry().get(plugins or []),
        ignored_classes=IgnoredClasses(ignore, hierarchy),
    )


def mutated(
    source: str, ignore: Mapping[str, list[str]], plugins: list[str] | None = None
) -> set[str]:
    """Mutated annotations of *source* (a single module) with the given ignore rules."""
    found = finder(ignore, ClassHierarchy(), plugins)
    return {
        mutation.mutated
        for annotation in AnnotationFinder().find(Path("models.py"), source=source)
        for mutation in found.find(annotation)
    }


def write_project(root: Path, files: Mapping[str, str]) -> list[Path]:
    """Write *files* (relative path -> content) under *root*; return the paths."""
    paths = [root / name for name in files]
    for path, content in zip(paths, files.values(), strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return paths


def mutated_in_project(
    root: Path, files: Mapping[str, str], target: str, ignore: Mapping[str, list[str]]
) -> set[str]:
    """Mutated annotations of *target* in a project made of *files*."""
    paths = write_project(root, files)
    unreadable = root / "app" / "broken.py"
    unreadable.write_bytes(b"\xff\xfe not utf-8")
    hierarchy = ClassHierarchyBuilder().build([*paths, unreadable, root / "missing.py"])
    found = finder(ignore, hierarchy)
    return {
        mutation.mutated
        for annotation in AnnotationFinder().find(root / target)
        for mutation in found.find(annotation)
    }


FIELD = "from pydantic import BaseModel\n\nclass Item(BaseModel):\n    name: str\n"


@pytest.mark.parametrize(
    "ignore,expected",
    [
        pytest.param({}, {"str | None"}, id="nothing-ignored"),
        pytest.param({"add-optional": [RESPONSE]}, set(), id="ignored-base"),
        pytest.param({"all": [RESPONSE]}, set(), id="all-operators"),
        pytest.param({"add-optional": ["pydantic.*"]}, set(), id="glob"),
        pytest.param({"add-optional": ["models.Item"]}, set(), id="class-itself"),
        pytest.param({"add-optional": ["other.Base"]}, {"str | None"}, id="other-class"),
        pytest.param({"remove-optional": [RESPONSE]}, {"str | None"}, id="other-operator"),
    ],
)
def test_fields_of_ignored_classes(ignore: dict[str, list[str]], expected: set[str]) -> None:
    assert mutated(FIELD, ignore) == expected


@pytest.mark.parametrize(
    "ignore,expected",
    [
        pytest.param({"add-optional": [RESPONSE]}, {"Sequence[str]"}, id="add-optional"),
        pytest.param(
            {"widen-container-type": [RESPONSE]}, {"list[str] | None"}, id="widen-container"
        ),
        pytest.param({"all": ["nothing.*"], "add-optional": [RESPONSE]}, {"Sequence[str]"}),
    ],
)
def test_ignore_is_per_operator(ignore: dict[str, list[str]], expected: set[str]) -> None:
    source = "from pydantic import BaseModel\n\nclass Item(BaseModel):\n    tags: list[str]\n"
    assert mutated(source, ignore) == expected


def test_methods_of_ignored_classes_are_mutated() -> None:
    source = (
        "from pydantic import BaseModel\n\n"
        "class Item(BaseModel):\n"
        "    def label(self) -> str:\n"
        "        text: int = 1\n"
        "        return str(text)\n"
    )
    assert mutated(source, {"all": [RESPONSE]}) == {"str | None", "int | None"}


def test_module_level_variables_are_mutated() -> None:
    source = "from pydantic import BaseModel\n\nname: str\n"
    assert mutated(source, {"all": [RESPONSE]}) == {"str | None"}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "import pydantic\n\nclass Item(pydantic.BaseModel):\n    name: str\n",
            id="dotted-base",
        ),
        pytest.param(
            "from pydantic import BaseModel as Model\n\nclass Item(Model):\n    name: str\n",
            id="aliased-base",
        ),
        pytest.param(
            "from typing import Generic\n"
            "from pydantic import BaseModel\n\n"
            "class Item(Generic[T], BaseModel, metaclass=Meta):\n"
            "    name: str\n",
            id="several-bases",
        ),
        pytest.param(
            "from pydantic import BaseModel\n\n"
            "class Item(BaseModel):\n"
            "    if True:\n"
            "        name: str\n",
            id="field-in-block",
        ),
    ],
)
def test_bases_are_resolved_through_imports(source: str) -> None:
    assert mutated(source, {"add-optional": [RESPONSE]}) == set()


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("typing.Generic", id="subscripted-base"),
        pytest.param("Exception", id="builtin-base"),
    ],
)
def test_bases_without_project_hierarchy(pattern: str) -> None:
    source = (
        "from typing import Generic\n\n"
        "class Item(Generic[T], Exception):\n"
        "    name: str\n"
    )
    assert mutated(source, {"add-optional": [pattern]}) == set()


@pytest.mark.parametrize(
    "pattern,expected",
    [
        pytest.param("models.Outer", {"str | None"}, id="outer-base-not-inherited"),
        pytest.param("models.Outer.*", set(), id="nested-name"),
        pytest.param("models.Base", set(), id="same-module-base"),
    ],
)
def test_nested_classes(pattern: str, expected: set[str]) -> None:
    source = (
        "class Base:\n    pass\n\n"
        "class Outer:\n"
        "    class Inner(Base):\n"
        "        name: str\n"
    )
    assert mutated(source, {"add-optional": [pattern]}) == expected


def test_class_without_bases_is_matched_by_its_own_name() -> None:
    source = "class Item():\n    name: str\n"
    assert mutated(source, {"add-optional": ["models.Item"]}) == set()


def test_plugin_still_mutates_fields_of_ignored_classes() -> None:
    source = (
        "from sqlalchemy.orm import DeclarativeBase, Mapped\n\n"
        "class User(DeclarativeBase):\n"
        "    id: Mapped[int]\n"
    )
    ignore = {"all": ["sqlalchemy.orm.DeclarativeBase"]}
    assert mutated(source, ignore, plugins=["sqlalchemy"]) == {"int | None"}


PROJECT = {
    "app/__init__.py": "",
    "app/api/__init__.py": "from app.api.base import BaseResponse\n",
    "app/api/base.py": "from pydantic import BaseModel\n\nclass BaseResponse(BaseModel): ...\n",
    "app/api/lists.py": "from app.api import BaseResponse\n\nclass ListResponse(BaseResponse): ...\n",
    "app/views.py": (
        "from .api.lists import ListResponse\n\n"
        "class ItemResponse(ListResponse):\n"
        "    name: str\n\n"
        "class Form:\n"
        "    title: int\n\n"
        "class Loop(Cycle):\n"
        "    size: float\n\n"
        "class Cycle(Loop): ...\n"
    ),
}


@pytest.mark.parametrize(
    "pattern,expected",
    [
        pytest.param("nothing.*", {"str | None", "int | None", "float | None"}, id="none"),
        pytest.param("app.api.base.BaseResponse", {"int | None", "float | None"}, id="base"),
        pytest.param("app.api.BaseResponse", {"int | None", "float | None"}, id="re-export"),
        pytest.param("pydantic.BaseModel", {"int | None", "float | None"}, id="library-base"),
        pytest.param("app.api.lists.ListResponse", {"int | None", "float | None"}, id="direct"),
        pytest.param("app.views.Form", {"str | None", "float | None"}, id="class-itself"),
        pytest.param("app.views.Cycle", {"str | None", "int | None"}, id="inheritance-cycle"),
    ],
)
def test_bases_are_resolved_across_project_modules(
    tmp_path: Path, pattern: str, expected: set[str]
) -> None:
    ignore = {"add-optional": [pattern]}
    assert mutated_in_project(tmp_path, PROJECT, "app/views.py", ignore) == expected


def test_warn_unknown_keys(caplog: pytest.LogCaptureFixture) -> None:
    ignored = IgnoredClasses({"all": ["x.*"], "widen-typ": ["x.Z"]}, ClassHierarchy())
    ignored.warn_unknown_keys(frozenset({"widen-type"}))
    assert "Ignoring unknown operator 'widen-typ' in 'ignore-classes'" in caplog.text
    assert "'all' in" not in caplog.text


def test_qualified_name_of_package_module(tmp_path: Path) -> None:
    write_project(tmp_path, {"app/__init__.py": "", "app/sub/__init__.py": ""})
    assert ClassNames().module_name(tmp_path / "app" / "sub" / "__init__.py") == "app.sub"


def test_init_applies_ignore_classes(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        root = Path(td)
        (root / "typemut.toml").write_text(
            '[typemut]\nmodule-path = "src"\ntest-command = "true"\n\n'
            '[typemut.ignore-classes]\nadd-optional = ["app.base.Response"]\n'
        )
        write_project(
            root / "src",
            {
                "app/__init__.py": "",
                "app/base.py": "class Response: ...\n",
                "app/items.py": (
                    "from app.base import Response\n\n"
                    "class Item(Response):\n"
                    "    name: str\n\n"
                    "class Form:\n"
                    "    title: int\n"
                ),
            },
        )
        result = runner.invoke(main, ["init"])
        with Database(root / "typemut.sqlite") as db:
            mutants = {mutant.mutated_annotation for mutant in db.get_all()}
    assert result.exit_code == 0
    assert mutants == {"int | None"}
