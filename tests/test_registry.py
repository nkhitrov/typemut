"""Tests for registry."""

from __future__ import annotations

from pathlib import Path

from typemut.registry import Registry


def test_hierarchy_from_fixture(fixtures_dir: Path):
    files = [fixtures_dir / "pydantic_models.py"]
    reg = Registry.from_files(files)

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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
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
    reg = Registry.from_files([src])
    assert reg.get_base_import_line("BaseModel") is None
