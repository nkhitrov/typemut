"""Tests for the pydantic plugin."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.db import Database
from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import RegistryBuilder

# (file, line, operator, original, mutated)
Found = tuple[str, int, str, str, str]

MODELS = """\
from collections.abc import Generator, Iterator, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel


class Item(BaseModel):
    name: str


class Base(BaseModel):
    pass


class Child(Base):
    name: str


class Username(str):
    pass
"""

PETS = """\
from typing import Literal

from pydantic import BaseModel


class Pet(BaseModel):
    pass


class Cat(Pet):
    pet_type: Literal["cat"]
    color: Literal["black", "white"]


class Dog(Pet):
    pet_type: Literal["dog"]
"""


def mutations(root: Path, files: dict[str, str], plugins: list[str]) -> set[Found]:
    """Mutations of every annotation of a project made of *files*, by file and line."""
    paths = []
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        paths.append(path)
    loaded = PluginRegistry().get(plugins)
    for plugin in loaded:
        plugin.scan(paths)
    finder = MutationFinder(OperatorRegistry().enabled({}), RegistryBuilder().build(paths), loaded)
    return {
        (path.name, mutation.line, mutation.operator, mutation.original, mutation.mutated)
        for path in paths
        for annotation in AnnotationFinder().find(path)
        for mutation in finder.find(annotation)
    }


FIELD_CASES = [
    pytest.param(
        {"api.py": "from models import Item, BaseModel\nclass Order(BaseModel):\n    item: Item\n"},
        ("api.py", 3, "WidenType", "Item", "BaseModel"),
        id="widen-to-base-model",
    ),
    pytest.param(
        {
            "api.py": "from models import Item, BaseModel\n"
            "class Order(BaseModel):\n    items: list[Item]\n"
        },
        ("api.py", 3, "WidenType", "Item", "BaseModel"),
        id="widen-to-base-model-nested",
    ),
    pytest.param(
        {
            "api.py": "from pydantic_settings import BaseSettings\nfrom models import Item\n"
            "class Settings(BaseSettings):\n    item: Item\n"
        },
        ("api.py", 4, "WidenType", "Item", "BaseModel"),
        id="settings-field",
    ),
    pytest.param(
        {
            "api.py": "from collections.abc import Sequence\nfrom models import Child\n"
            "class Order(Child):\n    ids: Sequence[int]\n"
        },
        ("api.py", 4, "WidenContainerType", "Sequence[int]", "Collection[int]"),
        id="no-schema-in-model-of-project-hierarchy",
    ),
    pytest.param(
        {
            "api.py": "from collections.abc import Sequence\nfrom pydantic import RootModel\n"
            "class Ids(RootModel[Sequence[int]]):\n    root: Sequence[int]\n"
        },
        ("api.py", 4, "WidenContainerType", "Sequence[int]", "Collection[int]"),
        id="no-schema-in-subscripted-root-model",
    ),
    pytest.param(
        {
            "api.py": "from collections.abc import Mapping\nimport pydantic.dataclasses\n"
            "@pydantic.dataclasses.dataclass(frozen=True)\n"
            "class Prices:\n    by_name: Mapping[str, float]\n"
        },
        ("api.py", 5, "WidenContainerType", "Mapping[str, float]", "Collection[str]"),
        id="no-schema-in-pydantic-dataclass",
    ),
    pytest.param(
        {
            "api.py": "from collections.abc import Generator\nfrom pydantic import BaseModel\n"
            "class Feed(BaseModel):\n    items: Generator[int, None, None]\n"
        },
        ("api.py", 4, "SwapIteratorGenerator", "Generator[int, None, None]", "Iterator[int]"),
        id="no-schema-iterator",
    ),
    pytest.param(
        {
            "api.py": "from pydantic import BaseModel, Field\nfrom pets import Cat, Dog\n"
            "class Owner(BaseModel):\n"
            "    pet: Cat | Dog = Field(discriminator='pet_type')\n"
        },
        ("pets.py", 11, "AddOptional", 'Literal["cat"]', 'Literal["cat"] | None'),
        id="discriminator-in-other-module",
    ),
    pytest.param(
        {
            "api.py": "from typing import Annotated\n"
            "from pydantic import BaseModel, Discriminator\nfrom pets import Cat, Dog\n"
            "class Owner(BaseModel):\n"
            "    pet: Annotated[Cat | Dog, Discriminator('color')]\n"
        },
        (
            "pets.py",
            12,
            "AddOptional",
            'Literal["black", "white"]',
            'Literal["black", "white"] | None',
        ),
        id="discriminator-class",
    ),
    pytest.param(
        {
            "api.py": "from pydantic import BaseModel, Field\nfrom pets import Cat, Dog\n"
            "class Owner(BaseModel):\n"
            "    pet: Cat | Dog = Field(discriminator='pet_type')\n"
        },
        ("api.py", 4, "WidenType", "Cat", "Pet"),
        id="widen-discriminated-member",
    ),
    pytest.param(
        {
            "api.py": "from typing import Annotated\nfrom pydantic import BaseModel, Field\n"
            "from pets import Cat, Dog\nclass Owner(BaseModel):\n"
            "    pet: Annotated[Cat | Dog, Field(discriminator='pet_type')]\n"
        },
        ("api.py", 5, "WidenType", "Dog", "Pet"),
        id="widen-annotated-discriminated-member",
    ),
]


@pytest.mark.parametrize(("files", "mutation"), FIELD_CASES)
def test_core_mutates_model_fields(tmp_path: Path, files: dict[str, str], mutation: Found) -> None:
    project = {"models.py": MODELS, "pets.py": PETS, **files}
    assert mutation in mutations(tmp_path, project, [])


@pytest.mark.parametrize(("files", "mutation"), FIELD_CASES)
def test_drops_mutations_pydantic_rejects(
    tmp_path: Path, files: dict[str, str], mutation: Found
) -> None:
    project = {"models.py": MODELS, "pets.py": PETS, **files}
    assert mutation not in mutations(tmp_path, project, ["pydantic"])


@pytest.mark.parametrize(
    ("files", "mutation"),
    [
        pytest.param(
            {"api.py": "from models import Item\ndef load() -> Item: ...\n"},
            ("api.py", 2, "WidenType", "Item", "BaseModel"),
            id="widen-to-base-model-outside-fields",
        ),
        pytest.param(
            {"api.py": "from models import Item\nclass Plain:\n    item: Item\n"},
            ("api.py", 3, "WidenType", "Item", "BaseModel"),
            id="field-of-plain-class",
        ),
        pytest.param(
            {
                "api.py": "from models import Child, BaseModel\nclass Order(BaseModel):\n    c: Child\n"
            },
            ("api.py", 3, "WidenType", "Child", "Base"),
            id="widen-to-project-model",
        ),
        pytest.param(
            {
                "api.py": "from models import Username, BaseModel\nclass User(BaseModel):\n    name: Username\n"
            },
            ("api.py", 3, "WidenType", "Username", "str"),
            id="widen-to-builtin",
        ),
        pytest.param(
            {
                "api.py": "from collections.abc import Sequence\nfrom models import BaseModel\n"
                "class Order(BaseModel):\n    def total(self) -> None:\n"
                "        ids: Sequence[int] = ()\n"
            },
            ("api.py", 5, "WidenContainerType", "Sequence[int]", "Collection[int]"),
            id="variable-in-method",
        ),
        pytest.param(
            {
                "api.py": "from collections.abc import Sequence\n"
                "def total(ids: Sequence[int]) -> Sequence[int]: ...\n"
            },
            ("api.py", 2, "WidenContainerType", "Sequence[int]", "Collection[int]"),
            id="no-schema-outside-fields",
        ),
        pytest.param(
            {
                "api.py": "from collections.abc import Iterator\nfrom models import BaseModel\n"
                "class Feed(BaseModel):\n    items: Iterator[int]\n"
            },
            ("api.py", 4, "AddOptional", "Iterator[int]", "Iterator[int] | None"),
            id="no-schema-type-already-there",
        ),
        pytest.param(
            {
                "api.py": "from typing import Literal\nfrom models import BaseModel\n"
                "class File(BaseModel):\n    mode: Literal['r', 'w']\n"
            },
            ("api.py", 4, "AddOptional", "Literal['r', 'w']", "Literal['r', 'w'] | None"),
            id="literal-not-a-discriminator",
        ),
        pytest.param(
            {
                "api.py": "from pydantic import BaseModel, Field\nfrom pets import Cat, Dog\n"
                "class Owner(BaseModel):\n"
                "    pet: Cat | Dog = Field(discriminator='pet_type')\n"
                "    kind: str\n"
            },
            ("api.py", 4, "AddOptional", "Cat | Dog", "Cat | Dog | None"),
            id="optional-discriminated-union",
        ),
        pytest.param(
            {
                "api.py": "from pydantic import BaseModel, Field\nfrom pets import Cat, Dog\n"
                "class Owner(BaseModel):\n"
                "    pet: Cat | Dog = Field(discriminator='pet_type')\n"
                "    pet_type: str\n"
            },
            ("api.py", 5, "AddOptional", "str", "str | None"),
            id="discriminator-name-without-literal",
        ),
        pytest.param(
            {
                "api.py": "from pydantic import BaseModel, Discriminator, Field\n"
                "from pets import Cat, Dog\nkey = 'color'\n"
                "class Owner(BaseModel):\n"
                "    a: Cat | Dog = Field(discriminator=key)\n"
                "    b: Cat | Dog = Field(discriminator=b'color')\n"
                "    c: Cat | Dog = Field(discriminator=Discriminator(lambda v: v))\n"
                "    d: Cat | Dog = Field(discriminator=Discriminator())\n"
                "    e: Cat | Dog = Field(**{'discriminator': 'color'})\n"
            },
            (
                "pets.py",
                12,
                "AddOptional",
                'Literal["black", "white"]',
                'Literal["black", "white"] | None',
            ),
            id="no-string-discriminator",
        ),
    ],
)
def test_keeps_mutations_pydantic_accepts(
    tmp_path: Path, files: dict[str, str], mutation: Found
) -> None:
    project = {"models.py": MODELS, "pets.py": PETS, **files}
    assert mutation in mutations(tmp_path, project, ["pydantic"])


HANDLERS = """\
from collections.abc import Sequence
from typing import Annotated, Any, Self

import pydantic
from pydantic import (
    AfterValidator,
    BaseModel,
    PlainSerializer,
    computed_field,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.functional_validators import model_validator as mv


def is_even(value: int) -> int:
    return value


def fmt(value: int) -> str:
    return str(value)


def unused(value: int) -> int:
    return value


class Model(BaseModel):
    number: Annotated[int, AfterValidator(func=is_even), PlainSerializer(fmt, when_used="json")]
    other: Annotated[int, AfterValidator(lambda v: v), AfterValidator()]

    @field_validator("number")
    @classmethod
    def check(cls, value: int) -> int:
        ids: Sequence[int] = ()
        return value

    @pydantic.field_validator("number", mode="before")
    @classmethod
    def before(cls, value: Any) -> int:
        return int(value)

    @model_validator(mode="after")
    def after(self) -> Self:
        return self

    @mv(mode="after")
    def aliased(self) -> Self:
        return self

    @field_serializer("number")
    def ser_number(self, value: int) -> str:
        return str(value)

    @model_serializer
    def ser_model(self) -> dict[str, int]:
        return {}

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> str:
        return ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def double(self) -> int:
        return self.number * 2

    def plain(self) -> int:
        return self.number


def outer() -> None:
    def model_post_init() -> int:
        return 0
"""


HANDLER_CASES = [
    pytest.param(18, "int", id="annotated-validator-keyword"),
    pytest.param(22, "str", id="annotated-serializer"),
    pytest.param(36, "int", id="field-validator"),
    pytest.param(42, "int", id="module-qualified-decorator"),
    pytest.param(46, "Self", id="model-validator"),
    pytest.param(50, "Self", id="aliased-decorator"),
    pytest.param(54, "str", id="field-serializer"),
    pytest.param(58, "dict[str, int]", id="bare-model-serializer"),
    pytest.param(62, "str", id="core-schema-hook"),
]


@pytest.mark.parametrize(("line", "original"), HANDLER_CASES)
def test_core_mutates_handler_signatures(tmp_path: Path, line: int, original: str) -> None:
    found = mutations(tmp_path, {"handlers.py": HANDLERS}, [])
    assert ("handlers.py", line, "AddOptional", original, f"{original} | None") in found


@pytest.mark.parametrize(("line", "original"), HANDLER_CASES)
def test_skips_signatures_pydantic_calls(tmp_path: Path, line: int, original: str) -> None:
    found = mutations(tmp_path, {"handlers.py": HANDLERS}, ["pydantic"])
    assert ("handlers.py", line, "AddOptional", original, f"{original} | None") not in found


@pytest.mark.parametrize(
    ("line", "operator", "original", "mutated"),
    [
        pytest.param(26, "AddOptional", "int", "int | None", id="function-not-passed"),
        pytest.param(37, "WidenContainerType", "Sequence[int]", "Collection[int]", id="body"),
        pytest.param(67, "AddOptional", "int", "int | None", id="computed-field"),
        pytest.param(70, "AddOptional", "int", "int | None", id="plain-method"),
        pytest.param(75, "AddOptional", "int", "int | None", id="hook-name-outside-class"),
    ],
)
def test_mutates_other_functions(
    tmp_path: Path, line: int, operator: str, original: str, mutated: str
) -> None:
    found = mutations(tmp_path, {"handlers.py": HANDLERS}, ["pydantic"])
    assert ("handlers.py", line, operator, original, mutated) in found


def test_scan_skips_unreadable_files(tmp_path: Path) -> None:
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe")
    plugin = PluginRegistry().get(["pydantic"])[0]
    plugin.scan([tmp_path / "missing.py", tmp_path / "binary.py"])
    found = mutations(tmp_path, {"pets.py": PETS}, ["pydantic"])
    assert ("pets.py", 11, "AddOptional", 'Literal["cat"]', 'Literal["cat"] | None') in found


def test_init_scans_the_project_for_discriminators(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        root = Path(td)
        (root / "typemut.toml").write_text(
            '[typemut]\nmodule-path = "src"\ntest-command = "true"\nplugins = ["pydantic"]\n'
        )
        (root / "src").mkdir()
        (root / "src" / "pets.py").write_text(PETS)
        (root / "src" / "owner.py").write_text(
            "from pydantic import BaseModel, Field\nfrom pets import Cat, Dog\n"
            "class Owner(BaseModel):\n    pet: Cat | Dog = Field(discriminator='pet_type')\n"
        )
        result = runner.invoke(main, ["init"])
        with Database(root / "typemut.sqlite") as db:
            found = {(m.line, m.operator, m.original_annotation) for m in db.get_all()}
    assert result.exit_code == 0
    assert (11, "AddOptional", 'Literal["cat"]') not in found
    assert (12, "AddOptional", 'Literal["black", "white"]') in found
