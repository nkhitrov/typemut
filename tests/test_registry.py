"""Tests for registry."""

from __future__ import annotations

from pathlib import Path

from typemut.registry import Registry, RegistryBuilder


def test_hierarchy_from_fixture(fixtures_dir: Path):
    files = [fixtures_dir / "pydantic_models.py"]
    reg = RegistryBuilder().build(files)

    assert "LoanState" in reg.hierarchy
    siblings = reg.get_siblings("ActiveLoan")
    assert "ClosedLoan" in siblings
    assert "OverdueLoan" in siblings
    assert "ActiveLoan" not in siblings


def test_no_siblings_for_unknown():
    reg = Registry()
    assert reg.get_siblings("Unknown") == []


def test_base_import_lines(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class User(BaseModel):\n"
        "    name: str\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base("User") == "BaseModel"
    assert reg.get_base_import_line("BaseModel") == "from pydantic import BaseModel"


def test_base_import_lines_local_class(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "class Base:\n"
        "    pass\n"
        "\n"
        "class Child(Base):\n"
        "    pass\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base("Child") == "Base"
    assert reg.get_base_import_line("Base") == "from models import Base"


def test_base_import_lines_from_defining_module(tmp_path: Path):
    """Regression test for #36: a base defined in a project module is imported from it."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "models.py").write_text(
        "class Animal:\n"
        "    pass\n"
        "\n"
        "class Cat(Animal):\n"
        "    pass\n"
    )
    reg = RegistryBuilder().build([package / "__init__.py", package / "models.py"])
    assert reg.get_base_import_line("Animal") == "from pkg.models import Animal"


def test_base_import_lines_from_defining_package(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import dataclasses\n"
        "\n"
        "@dataclasses.dataclass\n"
        "class Animal:\n"
        "    name: str\n"
    )
    (package / "cats.py").write_text(
        "from . import Animal\n"
        "\n"
        "class Cat(Animal):\n"
        "    pass\n"
    )
    reg = RegistryBuilder().build([package / "__init__.py", package / "cats.py"])
    assert reg.get_base_import_line("Animal") == "from pkg import Animal"


def test_base_import_lines_prefer_child_import(tmp_path: Path):
    (tmp_path / "animals.py").write_text("class Animal:\n    pass\n")
    (tmp_path / "cats.py").write_text(
        "from zoo.animals import Animal\n"
        "\n"
        "class Cat(Animal):\n"
        "    pass\n"
    )
    reg = RegistryBuilder().build([tmp_path / "animals.py", tmp_path / "cats.py"])
    assert reg.get_base_import_line("Animal") == "from zoo.animals import Animal"


def test_nested_class_has_no_import_line(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "class Outer:\n"
        "    class Base:\n"
        "        pass\n"
        "\n"
        "    class Child(Base):\n"
        "        pass\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base("Child") == "Base"
    assert reg.get_base_import_line("Base") is None


def test_base_import_lines_try_except(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "try:\n"
        "    from pydantic.generics import GenericModel\n"
        "except ImportError:\n"
        "    from pydantic import BaseModel as GenericModel\n"
        "\n"
        "class Result(GenericModel):\n"
        "    value: int\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base("Result") == "GenericModel"
    assert reg.get_base_import_line("GenericModel") == "from pydantic.generics import GenericModel"


def test_base_import_lines_try_fallback_does_not_override(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "try:\n"
        "    from new_lib import Base\n"
        "except ImportError:\n"
        "    from old_lib import Base\n"
        "finally:\n"
        "    pass\n"
        "\n"
        "class Child(Base):\n"
        "    pass\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base_import_line("Base") == "from new_lib import Base"


def test_base_import_lines_if_type_checking(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from pydantic import BaseModel\n"
        "else:\n"
        "    BaseModel = object\n"
        "\n"
        "class User(BaseModel):\n"
        "    name: str\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base_import_line("BaseModel") == "from pydantic import BaseModel"


def test_base_import_lines_ignore_function_body(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "def load():\n"
        "    from pydantic import BaseModel\n"
        "    return BaseModel\n"
        "\n"
        "class User(BaseModel):\n"
        "    name: str\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base("User") == "BaseModel"
    assert reg.get_base_import_line("BaseModel") is None


def test_base_import_lines_ignore_class_body_in_if(tmp_path: Path):
    src = tmp_path / "models.py"
    src.write_text(
        "if True:\n"
        "    class Holder:\n"
        "        from pydantic import BaseModel\n"
        "\n"
        "class User(BaseModel):\n"
        "    name: str\n"
    )
    reg = RegistryBuilder().build([src])
    assert reg.get_base_import_line("BaseModel") is None
