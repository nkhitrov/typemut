"""Tests for imports module — type origin registry and import injection."""

from __future__ import annotations

from typemut.imports import (
    add_import,
    detect_preferred_module,
    extract_type_name,
    find_last_import_line,
    needs_import,
)


# --- extract_type_name ---


def test_extract_subscripted():
    assert extract_type_name("Sequence[int]") == "Sequence"


def test_extract_multi_param():
    assert extract_type_name("Generator[int, None, None]") == "Generator"


def test_extract_plain():
    assert extract_type_name("int") == "int"


def test_extract_with_spaces():
    assert extract_type_name("  Mapping[str, int]  ") == "Mapping"


# --- needs_import ---


def test_builtin_no_import():
    assert needs_import("x: list\n", "list") is False


def test_unknown_type_no_import():
    assert needs_import("x: MyClass\n", "MyClass") is False


def test_already_imported():
    source = "from collections.abc import Sequence\n\nx: list\n"
    assert needs_import(source, "Sequence") is False


def test_already_imported_typing():
    source = "from typing import Sequence\n\nx: list\n"
    assert needs_import(source, "Sequence") is False


def test_already_imported_multi_name():
    source = "from collections.abc import Iterable, Sequence, Mapping\n"
    assert needs_import(source, "Sequence") is False


def test_already_imported_parenthesized():
    source = (
        "from collections.abc import (\n"
        "    Iterable,\n"
        "    Sequence,\n"
        ")\n"
    )
    assert needs_import(source, "Sequence") is False


def test_needs_import_not_present():
    source = "from typing import List\n\nx: list[int]\n"
    assert needs_import(source, "Sequence") is True


def test_needs_import_iterator():
    source = "x: Iterator[int]\n"
    assert needs_import(source, "Iterator") is True


# --- detect_preferred_module ---


def test_prefer_typing_when_used():
    source = "from typing import List\n\nx: List[int]\n"
    assert detect_preferred_module(source, "Sequence") == "typing"


def test_prefer_collections_abc_when_used():
    source = "from collections.abc import Iterable\n\nx: Iterable[int]\n"
    assert detect_preferred_module(source, "Sequence") == "collections.abc"


def test_default_to_collections_abc():
    source = "x: list[int]\n"
    assert detect_preferred_module(source, "Sequence") == "collections.abc"


# --- find_last_import_line ---


def test_find_last_import_simple():
    lines = [
        "from __future__ import annotations\n",
        "import os\n",
        "from pathlib import Path\n",
        "\n",
        "x = 1\n",
    ]
    assert find_last_import_line(lines) == 2


def test_find_last_import_parenthesized():
    lines = [
        "from typing import (\n",
        "    List,\n",
        "    Dict,\n",
        ")\n",
        "\n",
        "x = 1\n",
    ]
    assert find_last_import_line(lines) == 3


def test_find_last_import_none():
    lines = ["x = 1\n", "y = 2\n"]
    assert find_last_import_line(lines) == -1


# --- add_import ---


def test_add_import_new_line():
    source = "import os\n\nx: list[int]\n"
    new_source, inserted_at = add_import(source, "Sequence", "collections.abc")
    assert "from collections.abc import Sequence\n" in new_source
    assert inserted_at == 1
    # Original content still present
    assert "x: list[int]" in new_source


def test_add_import_appends_to_existing():
    source = "from collections.abc import Iterable\n\nx: list[int]\n"
    new_source, inserted_at = add_import(source, "Sequence", "collections.abc")
    assert "from collections.abc import Iterable, Sequence\n" in new_source
    assert inserted_at is None  # no new line inserted


def test_add_import_after_future():
    source = "from __future__ import annotations\n\nx: list[int]\n"
    new_source, inserted_at = add_import(source, "Sequence", "collections.abc")
    lines = new_source.splitlines()
    assert lines[0] == "from __future__ import annotations"
    assert lines[1] == "from collections.abc import Sequence"
    assert inserted_at == 1


def test_add_import_no_existing_imports():
    source = "x: list[int]\n"
    new_source, inserted_at = add_import(source, "Sequence", "collections.abc")
    lines = new_source.splitlines()
    assert lines[0] == "from collections.abc import Sequence"
    assert inserted_at == 0


def test_add_import_typing():
    source = "from typing import List\n\nx: List[int]\n"
    new_source, inserted_at = add_import(source, "Sequence", "typing")
    assert "from typing import List, Sequence\n" in new_source
    assert inserted_at is None
