"""Tests for registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.registry import Registry, RegistryBuilder, Widening


def widening(root: Path, sources: dict[str, str], file: str, name: str) -> Widening | None:
    """Widening of *name* as written in *file*, with the registry of all *sources*."""
    for path, source in sources.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(source)
    reg = RegistryBuilder().build(sorted(root.rglob("*.py")))
    return reg.in_file(root / file).widening(name)


def test_unknown_name_has_no_widening() -> None:
    assert Registry().in_file(Path("models.py")).widening("Unknown") is None


def test_unbound_registry_has_no_widening(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text("class Animal: ...\nclass Cat(Animal): ...\n")
    assert RegistryBuilder().build([tmp_path / "models.py"]).widening("Cat") is None


def test_hierarchy_from_fixture(fixtures_dir: Path) -> None:
    file = fixtures_dir / "pydantic_models.py"
    reg = RegistryBuilder().build([file]).in_file(file)

    assert reg.widening("ActiveLoan") == Widening(
        name="LoanState", qualified="tests.fixtures.pydantic_models.LoanState"
    )


def test_external_base_is_imported_like_the_child_imports_it(tmp_path: Path) -> None:
    sources = {
        "models.py": "from pydantic import BaseModel\n\nclass User(BaseModel):\n    name: str\n",
        "service.py": "from models import User\n",
    }
    assert widening(tmp_path, sources, "service.py", "User") == Widening(
        name="BaseModel",
        qualified="pydantic.BaseModel",
        required_import="from pydantic import BaseModel",
    )


def test_base_in_scope_needs_no_import(tmp_path: Path) -> None:
    sources = {"models.py": "class Base:\n    pass\n\nclass Child(Base):\n    pass\n"}
    assert widening(tmp_path, sources, "models.py", "Child") == Widening(
        name="Base", qualified="models.Base"
    )


def test_base_from_defining_module(tmp_path: Path) -> None:
    """Regression test for #36: a base defined in a project module is imported from it."""
    sources = {
        "pkg/__init__.py": "",
        "pkg/models.py": "class Animal:\n    pass\n\nclass Cat(Animal):\n    pass\n",
        "pkg/service.py": "from pkg.models import Cat\n",
    }
    assert widening(tmp_path, sources, "pkg/service.py", "Cat") == Widening(
        name="Animal",
        qualified="pkg.models.Animal",
        required_import="from pkg.models import Animal",
    )


def test_base_from_defining_package(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "import dataclasses\n\n@dataclasses.dataclass\nclass Animal:\n    name: str\n",
        "pkg/cats.py": "from . import Animal\n\nclass Cat(Animal):\n    pass\n",
        "pkg/service.py": "from pkg.cats import Cat\n",
    }
    assert widening(tmp_path, sources, "pkg/service.py", "Cat") == Widening(
        name="Animal", qualified="pkg.Animal", required_import="from pkg import Animal"
    )


def test_base_under_its_alias_in_the_file(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "",
        "pkg/models.py": "class Animal:\n    pass\n\nclass Cat(Animal):\n    pass\n",
        "pkg/service.py": "from pkg.models import Animal as Pet, Cat\n",
    }
    assert widening(tmp_path, sources, "pkg/service.py", "Cat") == Widening(
        name="Pet", qualified="pkg.models.Animal"
    )


def test_same_named_classes_in_other_modules(tmp_path: Path) -> None:
    """Classes are told apart by qualified name, not by the name they are written with."""
    sources = {
        "extra_models.py": "class UserBase: ...\nclass UserInDB(UserBase): ...\n",
        "security.py": "class User: ...\nclass UserInDB(User): ...\n",
    }
    assert widening(tmp_path, sources, "extra_models.py", "UserInDB") == Widening(
        name="UserBase", qualified="extra_models.UserBase"
    )


def test_imported_class_shadowing_a_project_class(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "",
        "pkg/models.py": "class BaseModelWithConfig: ...\nclass Response(BaseModelWithConfig): ...\n",
        "pkg/routing.py": "from starlette.responses import Response\n",
    }
    assert widening(tmp_path, sources, "pkg/routing.py", "Response") is None


def test_class_imported_through_a_reexport(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "from .models import Cat\n",
        "pkg/models.py": "class Animal: ...\nclass Cat(Animal): ...\n",
        "service.py": "from pkg import Cat\n",
    }
    assert widening(tmp_path, sources, "service.py", "Cat") == Widening(
        name="Animal",
        qualified="pkg.models.Animal",
        required_import="from pkg.models import Animal",
    )


def test_reexport_cycle_ends(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "from pkg.a import Cat\n",
        "pkg/a.py": "from pkg import Cat\n",
        "service.py": "from pkg import Cat\n",
    }
    assert widening(tmp_path, sources, "service.py", "Cat") is None


def test_base_assigned_by_an_alias_is_skipped(tmp_path: Path) -> None:
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
        "broker.py": "from state import TaskiqState\n",
    }
    assert widening(tmp_path, sources, "broker.py", "TaskiqState") is None


def test_base_imported_from_a_project_module_that_does_not_define_it(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "",
        "pkg/state.py": "_Base = dict\n",
        "pkg/models.py": "from pkg.state import _Base\nclass State(_Base): ...\n",
        "pkg/service.py": "from pkg.models import State\n",
    }
    assert widening(tmp_path, sources, "pkg/service.py", "State") is None


def test_conditionally_defined_base(tmp_path: Path) -> None:
    source = (
        "import sys\n"
        "if sys.version_info >= (3, 12):\n"
        "    class Base: ...\n"
        "else:\n"
        "    class Base: ...\n"
        "class Child(Base): ...\n"
    )
    sources = {"models.py": source, "service.py": "from models import Child\n"}
    assert widening(tmp_path, sources, "service.py", "Child") is None


def test_conditionally_defined_base_in_its_own_module(tmp_path: Path) -> None:
    source = "if True:\n    class Base: ...\nclass Child(Base): ...\n"
    assert widening(tmp_path, {"models.py": source}, "models.py", "Child") == Widening(
        name="Base", qualified="models.Base"
    )


def test_nested_base_is_skipped(tmp_path: Path) -> None:
    source = "class Outer:\n    class Base: ...\nclass Child(Outer.Base): ...\n"
    sources = {"models.py": source, "service.py": "from models import Child\n"}
    assert widening(tmp_path, sources, "service.py", "Child") is None


def test_base_name_bound_to_another_class_in_the_file(tmp_path: Path) -> None:
    sources = {
        "pkg/__init__.py": "",
        "pkg/params.py": "class Param: ...\nclass Header(Param): ...\n",
        "pkg/openapi.py": "from pkg.params import Header\nclass Param: ...\n",
    }
    assert widening(tmp_path, sources, "pkg/openapi.py", "Header") is None


def test_builtin_base_needs_no_import(tmp_path: Path) -> None:
    sources = {"errors.py": "class AppError(Exception): ...\n"}
    assert widening(tmp_path, sources, "errors.py", "AppError") == Widening(
        name="Exception", qualified="Exception"
    )


def test_unresolved_base_is_skipped(tmp_path: Path) -> None:
    sources = {"models.py": "from base import *\nclass Child(Base): ...\n"}
    assert widening(tmp_path, sources, "models.py", "Child") is None


def test_class_without_bases(tmp_path: Path) -> None:
    sources = {"models.py": "class Plain: ...\nclass Empty(): ...\n"}
    assert widening(tmp_path, sources, "models.py", "Empty") is None


def test_base_through_an_imported_module(tmp_path: Path) -> None:
    sources = {"models.py": "import pydantic\nclass User(pydantic.BaseModel): ...\n"}
    assert widening(tmp_path, sources, "models.py", "User") == Widening(
        name="pydantic.BaseModel", qualified="pydantic.BaseModel"
    )


def test_dotted_base_imported_by_name(tmp_path: Path) -> None:
    sources = {
        "models.py": "import pydantic\nclass User(pydantic.BaseModel): ...\n",
        "service.py": "from models import User\n",
    }
    assert widening(tmp_path, sources, "service.py", "User") == Widening(
        name="BaseModel",
        qualified="pydantic.BaseModel",
        required_import="from pydantic import BaseModel",
    )


@pytest.mark.parametrize(
    "bases,expected",
    [
        pytest.param(
            "Base, Generic[T]", Widening(name="Base", qualified="models.Base"), id="plain"
        ),
        pytest.param(
            "Base[T]",
            Widening(name="Base", qualified="models.Base", subscripted=True),
            id="subscripted",
        ),
        pytest.param(
            "metaclass=Meta",
            None,
            id="keyword-only",
        ),
        pytest.param("make_base()", None, id="call"),
    ],
)
def test_first_base(tmp_path: Path, bases: str, expected: Widening | None) -> None:
    source = f"class Base: ...\nclass Child({bases}): ...\n"
    assert widening(tmp_path, {"models.py": source}, "models.py", "Child") == expected


def test_try_import_wins_over_except_fallback(tmp_path: Path) -> None:
    source = (
        "try:\n"
        "    from pydantic.generics import GenericModel\n"
        "except ImportError:\n"
        "    from pydantic import BaseModel as GenericModel\n"
        "class Result(GenericModel):\n"
        "    value: int\n"
    )
    sources = {"models.py": source, "service.py": "from models import Result\n"}
    assert widening(tmp_path, sources, "service.py", "Result") == Widening(
        name="GenericModel",
        qualified="pydantic.generics.GenericModel",
        required_import="from pydantic.generics import GenericModel",
    )


def test_type_checking_import(tmp_path: Path) -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pydantic import BaseModel\n"
        "else:\n"
        "    BaseModel = object\n"
        "class User(BaseModel):\n"
        "    name: str\n"
    )
    sources = {"models.py": source, "service.py": "from models import User\n"}
    assert widening(tmp_path, sources, "service.py", "User") == Widening(
        name="BaseModel",
        qualified="pydantic.BaseModel",
        required_import="from pydantic import BaseModel",
    )


def test_imports_in_nested_scopes_bind_nothing(tmp_path: Path) -> None:
    source = (
        "def load():\n"
        "    from pydantic import BaseModel\n"
        "if True:\n"
        "    class Holder:\n"
        "        from pydantic import BaseModel\n"
        "class User(BaseModel): ...\n"
    )
    assert widening(tmp_path, {"models.py": source}, "models.py", "User") is None


def test_unreadable_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe")
    (tmp_path / "models.py").write_text("class Animal: ...\nclass Cat(Animal): ...\n")
    files = [tmp_path / "binary.py", tmp_path / "missing.py", tmp_path / "models.py"]
    reg = RegistryBuilder().build(files)
    assert reg.in_file(tmp_path / "models.py").widening("Cat") == Widening(
        name="Animal", qualified="models.Animal"
    )


def test_base_imported_under_an_alias_by_the_child(tmp_path: Path) -> None:
    sources = {
        "models.py": "from pydantic import BaseModel as BM\nclass User(BM): ...\n",
        "service.py": "from models import User\n",
    }
    assert widening(tmp_path, sources, "service.py", "User") == Widening(
        name="BaseModel",
        qualified="pydantic.BaseModel",
        required_import="from pydantic import BaseModel",
    )


def test_module_of_a_namespace_directory_inside_a_package(tmp_path: Path) -> None:
    """docs/examples is a package, its subdirectories have no ``__init__.py``."""
    sources = {
        "docs/examples/__init__.py": "",
        "docs/examples/core_concepts/glossary.py": (
            "class UserCreateModel: ...\nclass UserModel(UserCreateModel): ...\n"
        ),
        "docs/examples/error_handling/described.py": (
            "import msgspec\nclass UserModel(msgspec.Struct): ...\n"
        ),
        "docs/examples/auth/obtain.py": "from examples.core_concepts.glossary import UserModel\n",
    }
    assert widening(tmp_path, sources, "docs/examples/auth/obtain.py", "UserModel") == Widening(
        name="UserCreateModel",
        qualified="examples.core_concepts.glossary.UserCreateModel",
        required_import="from examples.core_concepts.glossary import UserCreateModel",
    )
    assert widening(
        tmp_path, sources, "docs/examples/error_handling/described.py", "UserModel"
    ) == Widening(name="msgspec.Struct", qualified="msgspec.Struct")
