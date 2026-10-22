"""Tests for imports module — type origin registry and import injection."""

from __future__ import annotations

import pytest

from typemut.imports import ImportInjector


# --- extract_type_name ---


def test_extract_subscripted():
    assert ImportInjector().type_name("Sequence[int]") == "Sequence"


def test_extract_multi_param():
    assert ImportInjector().type_name("Generator[int, None, None]") == "Generator"


def test_extract_plain():
    assert ImportInjector().type_name("int") == "int"


def test_extract_with_spaces():
    assert ImportInjector().type_name("  Mapping[str, int]  ") == "Mapping"


# --- needs_import ---


def test_builtin_no_import():
    assert ImportInjector().needs_import("x: list\n", "list") is False


def test_unknown_type_no_import():
    assert ImportInjector().needs_import("x: MyClass\n", "MyClass") is False


def test_already_imported():
    source = "from collections.abc import Sequence\n\nx: list\n"
    assert ImportInjector().needs_import(source, "Sequence") is False


def test_already_imported_typing():
    source = "from typing import Sequence\n\nx: list\n"
    assert ImportInjector().needs_import(source, "Sequence") is False


def test_already_imported_multi_name():
    source = "from collections.abc import Iterable, Sequence, Mapping\n"
    assert ImportInjector().needs_import(source, "Sequence") is False


def test_already_imported_parenthesized():
    source = (
        "from collections.abc import (\n"
        "    Iterable,\n"
        "    Sequence,\n"
        ")\n"
    )
    assert ImportInjector().needs_import(source, "Sequence") is False


def test_needs_import_not_present():
    source = "from typing import List\n\nx: list[int]\n"
    assert ImportInjector().needs_import(source, "Sequence") is True


def test_needs_import_iterator():
    source = "x: Iterator[int]\n"
    assert ImportInjector().needs_import(source, "Iterator") is True


# --- detect_preferred_module ---


def test_prefer_typing_when_used():
    source = "from typing import List\n\nx: List[int]\n"
    assert ImportInjector().preferred_module(source, "Sequence") == "typing"


def test_prefer_collections_abc_when_used():
    source = "from collections.abc import Iterable\n\nx: Iterable[int]\n"
    assert ImportInjector().preferred_module(source, "Sequence") == "collections.abc"


def test_default_to_collections_abc():
    source = "x: list[int]\n"
    assert ImportInjector().preferred_module(source, "Sequence") == "collections.abc"


# --- find_last_import_line ---


def test_find_last_import_simple():
    lines = [
        "from __future__ import annotations\n",
        "import os\n",
        "from pathlib import Path\n",
        "\n",
        "x = 1\n",
    ]
    assert ImportInjector().last_import_line(lines) == 2


def test_find_last_import_parenthesized():
    lines = [
        "from typing import (\n",
        "    List,\n",
        "    Dict,\n",
        ")\n",
        "\n",
        "x = 1\n",
    ]
    assert ImportInjector().last_import_line(lines) == 3


def test_find_last_import_none():
    lines = ["x = 1\n", "y = 2\n"]
    assert ImportInjector().last_import_line(lines) == -1


def test_find_last_import_ignores_docstrings():
    lines = [
        "import os\n",
        "\n",
        'def foo():\n',
        '    """\n',
        '    Get result from result dict.\n',
        '    """\n',
        '    pass\n',
    ]
    assert ImportInjector().last_import_line(lines) == 0


def test_find_last_import_ignores_indented():
    lines = [
        "import os\n",
        "\n",
        "def foo():\n",
        "    from bar import baz\n",
        "    pass\n",
    ]
    assert ImportInjector().last_import_line(lines) == 0


# --- add_import ---


def test_add_import_new_line():
    source = "import os\n\nx: list[int]\n"
    new_source, inserted_at = ImportInjector().add(source, "Sequence", "collections.abc")
    assert "from collections.abc import Sequence\n" in new_source
    assert inserted_at == 1
    # Original content still present
    assert "x: list[int]" in new_source


def test_add_import_appends_to_existing():
    source = "from collections.abc import Iterable\n\nx: list[int]\n"
    new_source, inserted_at = ImportInjector().add(source, "Sequence", "collections.abc")
    assert "from collections.abc import Iterable, Sequence\n" in new_source
    assert inserted_at is None  # no new line inserted


def test_add_import_after_future():
    source = "from __future__ import annotations\n\nx: list[int]\n"
    new_source, inserted_at = ImportInjector().add(source, "Sequence", "collections.abc")
    lines = new_source.splitlines()
    assert lines[0] == "from __future__ import annotations"
    assert lines[1] == "from collections.abc import Sequence"
    assert inserted_at == 1


def test_add_import_no_existing_imports():
    source = "x: list[int]\n"
    new_source, inserted_at = ImportInjector().add(source, "Sequence", "collections.abc")
    lines = new_source.splitlines()
    assert lines[0] == "from collections.abc import Sequence"
    assert inserted_at == 0


def test_add_import_typing():
    source = "from typing import List\n\nx: List[int]\n"
    new_source, inserted_at = ImportInjector().add(source, "Sequence", "typing")
    assert "from typing import List, Sequence\n" in new_source
    assert inserted_at is None


# --- add_import_line ---


def test_add_import_line_parses_and_merges():
    source = "from pydantic import Field\n\nx: int\n"
    new_source, inserted_at = ImportInjector().add_line(source, "from pydantic import BaseModel")
    assert "from pydantic import Field, BaseModel\n" in new_source
    assert inserted_at is None


def test_add_import_line_new_module():
    source = "import os\n\nx: int\n"
    new_source, inserted_at = ImportInjector().add_line(source, "from abc import ABC")
    assert "from abc import ABC\n" in new_source
    assert inserted_at == 1


# --- resolve_import ---


def test_resolve_with_required_import():
    source = "import os\n\nx: MyClass\n"
    new_source, inserted_at = ImportInjector().resolve(source, "BaseModel", "from pydantic import BaseModel")
    assert "from pydantic import BaseModel\n" in new_source
    assert inserted_at == 1


def test_resolve_required_import_already_present():
    source = "from pydantic import BaseModel\n\nx: MyClass\n"
    new_source, inserted_at = ImportInjector().resolve(source, "BaseModel", "from pydantic import BaseModel")
    assert new_source == source
    assert inserted_at is None


def test_resolve_required_import_of_class_defined_in_source():
    source = "class Animal:\n    pass\n\n\nclass Cat(Animal):\n    pass\n\n\npet: Cat\n"
    new_source, inserted_at = ImportInjector().resolve(source, "Animal", "from pkg.models import Animal")
    assert new_source == source
    assert inserted_at is None


def test_resolve_falls_back_to_import_sources():
    source = "import os\n\nx: list\n"
    new_source, inserted_at = ImportInjector().resolve(source, "Sequence[int]", None)
    assert "import Sequence" in new_source
    assert inserted_at is not None


def test_resolve_no_import_needed():
    source = "import os\n\nx: list\n"
    new_source, inserted_at = ImportInjector().resolve(source, "list", None)
    assert new_source == source
    assert inserted_at is None


# --- merging into existing imports of any shape ---


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from dmr.parsers import _NoOpParser  # pyright: ignore[reportPrivateUsage]\n",
            "from dmr.parsers import _NoOpParser, Parser  # pyright: ignore[reportPrivateUsage]\n",
            id="trailing-comment",
        ),
        pytest.param(
            "from dmr.parsers import Json  # type: ignore[attr-defined]\n",
            "from dmr.parsers import Json, Parser  # type: ignore[attr-defined]\n",
            id="type-ignore",
        ),
        pytest.param(
            "from dmr.parsers import Json  # noqa: F401\n",
            "from dmr.parsers import Json, Parser  # noqa: F401\n",
            id="noqa",
        ),
        pytest.param(
            "from dmr.parsers import Json as J  # noqa\n",
            "from dmr.parsers import Json as J, Parser  # noqa\n",
            id="alias",
        ),
        pytest.param(
            "from dmr.parsers import Json; import os\n",
            "from dmr.parsers import Json, Parser; import os\n",
            id="semicolon",
        ),
        pytest.param(
            "from dmr.parsers import Json, \\\n    Xml  # noqa\n",
            "from dmr.parsers import Json, \\\n    Xml, Parser  # noqa\n",
            id="backslash",
        ),
        pytest.param(
            "from dmr.parsers import (  # first\n    Json,  # json\n    Xml  # xml\n)  # last\n",
            "from dmr.parsers import (  # first\n    Json,  # json\n    Xml, Parser  # xml\n)  # last\n",
            id="parenthesized",
        ),
        pytest.param(
            "from dmr.parsers import (\n    Json,\n    Xml,  # xml\n)\n",
            "from dmr.parsers import (\n    Json,\n    Xml, Parser,  # xml\n)\n",
            id="parenthesized-trailing-comma",
        ),
        pytest.param(
            "from dmr.parsers import (Json)  # noqa\n",
            "from dmr.parsers import (Json, Parser)  # noqa\n",
            id="parenthesized-single-line",
        ),
        pytest.param(
            "from dmr.parsers import _NoOpParser  # pyright: ignore\n\nx: _NoOpParser\n",
            "from dmr.parsers import _NoOpParser, Parser  # pyright: ignore\n\nx: _NoOpParser\n",
            id="code-after",
        ),
        pytest.param(
            "from dmr.parsers import Parser as P\n",
            "from dmr.parsers import Parser as P, Parser\n",
            id="aliased-name-is-not-bound",
        ),
    ],
)
def test_resolve_merges_into_existing_import(source: str, expected: str) -> None:
    new_source, inserted_at = ImportInjector().resolve(source, "Parser", "from dmr.parsers import Parser")
    assert (new_source, inserted_at) == (expected, None)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from dmr.parsers import *\n",
            "from dmr.parsers import *\nfrom dmr.parsers import Parser\n",
            id="star",
        ),
        pytest.param(
            "from .parsers import Json\n",
            "from .parsers import Json\nfrom dmr.parsers import Parser\n",
            id="relative",
        ),
        pytest.param(
            "import dmr.parsers as parsers\n",
            "import dmr.parsers as parsers\nfrom dmr.parsers import Parser\n",
            id="module-alias",
        ),
        pytest.param(
            "from dmr.parsers_extra import Json\n",
            "from dmr.parsers_extra import Json\nfrom dmr.parsers import Parser\n",
            id="module-prefix",
        ),
        pytest.param(
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from dmr.parsers import Json\n",
            "from typing import TYPE_CHECKING\nfrom dmr.parsers import Parser\n\nif TYPE_CHECKING:\n"
            "    from dmr.parsers import Json\n",
            id="type-checking-module",
        ),
    ],
)
def test_resolve_adds_new_import_line(source: str, expected: str) -> None:
    new_source, inserted_at = ImportInjector().resolve(source, "Parser", "from dmr.parsers import Parser")
    assert (new_source, inserted_at) == (expected, expected.splitlines().index("from dmr.parsers import Parser"))


@pytest.mark.parametrize(
    ("source", "required_import"),
    [
        pytest.param("from dmr.parsers import Parser  # noqa\n", "from dmr.parsers import Parser", id="comment"),
        pytest.param("from dmr.parsers import (\n    Json,\n    Parser,  # p\n)\n", "from dmr.parsers import Parser", id="paren"),
        pytest.param("from dmr.parsers import Json as Parser\n", "from dmr.parsers import Parser", id="alias"),
        pytest.param(
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from dmr.parsers import Parser\n",
            "from dmr.parsers import Parser",
            id="type-checking",
        ),
        pytest.param("@final\nclass Parser:\n    pass\n", "from dmr.parsers import Parser", id="decorated-class"),
        pytest.param("import dmr.parsers as parsers\n", "import dmr.parsers as parsers", id="import-as"),
        pytest.param("import dmr.parsers\n", "import dmr.parsers", id="import"),
    ],
)
def test_resolve_does_not_duplicate_bound_name(source: str, required_import: str) -> None:
    assert ImportInjector().resolve(source, "Parser", required_import) == (source, None)


def test_resolve_ignores_name_imported_inside_function():
    source = "def f():\n    from dmr.parsers import Parser\n"
    new_source, inserted_at = ImportInjector().resolve(source, "Parser", "from dmr.parsers import Parser")
    assert (new_source, inserted_at) == ("from dmr.parsers import Parser\n" + source, 0)


def test_resolve_ignores_import_in_comment_and_docstring():
    source = '"""\nfrom dmr.parsers import Json\n"""\n# from dmr.parsers import Parser\nimport os\n'
    new_source, inserted_at = ImportInjector().resolve(source, "Parser", "from dmr.parsers import Parser")
    assert (new_source, inserted_at) == (source + "from dmr.parsers import Parser\n", 5)


def test_add_line_inserts_plain_import_after_last_import():
    source = "import os\n\nx: int\n"
    new_source, inserted_at = ImportInjector().add_line(source, "import dmr.parsers as parsers")
    assert (new_source, inserted_at) == ("import os\nimport dmr.parsers as parsers\n\nx: int\n", 1)


def test_add_does_not_duplicate_name_in_same_import():
    source = "from collections.abc import Iterable  # noqa\n"
    assert ImportInjector().add(source, "Iterable", "collections.abc") == (source, None)


def test_find_last_import_parenthesized_with_comments():
    lines = [
        "from typing import (  # (\n",
        "    List,  # )\n",
        ")\n",
        "x = '''\n",
        "import os\n",
        "'''\n",
    ]
    assert ImportInjector().last_import_line(lines) == 2


def test_find_last_import_backslash_continuation():
    lines = ["from typing import List, \\\n", "    Dict\n", "x = 1\n"]
    assert ImportInjector().last_import_line(lines) == 1
