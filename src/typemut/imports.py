"""Type origin registry and import injection for mutation targets.

When a mutation operator replaces a type with another (e.g. list -> Sequence),
the target type may not be imported in the file. This module provides:
- A central mapping of type names to their standard library modules
- Functions to detect existing imports and inject new ones
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Type origin classification
# ---------------------------------------------------------------------------

# Python builtins — no import needed.
BUILTIN_TYPES: frozenset[str] = frozenset({
    "list", "tuple", "set", "frozenset", "dict",
    "int", "str", "float", "bool", "bytes", "bytearray",
    "complex", "object", "type", "None", "memoryview",
})

# Types available from collections.abc (preferred for Python 3.9+)
# and also re-exported by typing for backwards compatibility.
# Key = type name, value = default module to import from.
IMPORT_SOURCES: dict[str, str] = {
    "Sequence": "collections.abc",
    "MutableSequence": "collections.abc",
    "AbstractSet": "collections.abc",
    "MutableSet": "collections.abc",
    "Mapping": "collections.abc",
    "MutableMapping": "collections.abc",
    "Collection": "collections.abc",
    "Iterable": "collections.abc",
    "Iterator": "collections.abc",
    "Generator": "collections.abc",
    "AsyncIterator": "collections.abc",
    "AsyncGenerator": "collections.abc",
    "AsyncIterable": "collections.abc",
}

# Legacy typing-capitalized forms (List, Tuple, etc.).
# If the original type uses these, the import is already in scope.
TYPING_GENERIC_ALIASES: frozenset[str] = frozenset({
    "List", "Tuple", "Set", "FrozenSet", "Dict",
    "Sequence",  # also exists in typing
})


def extract_type_name(annotation: str) -> str:
    """Extract the root type name from an annotation string.

    >>> extract_type_name("Sequence[int]")
    'Sequence'
    >>> extract_type_name("Generator[int, None, None]")
    'Generator'
    >>> extract_type_name("int")
    'int'
    """
    bracket = annotation.find("[")
    if bracket == -1:
        return annotation.strip()
    return annotation[:bracket].strip()


def _is_imported(source: str, type_name: str) -> bool:
    """Check whether *type_name* is already imported in *source*.

    Handles:
    - ``from X import type_name``
    - ``from X import (..., type_name, ...)``
    - ``import X`` where X == module containing type_name (qualified usage)
    """
    # Pattern: from <module> import <...type_name...>
    # Handles both single-line and multi-line (parenthesized) imports.
    pattern = re.compile(
        r"^from\s+\S+\s+import\s+"
        r"(?:"
        r"[^)]*\b" + re.escape(type_name) + r"\b"  # single-line
        r"|"
        r"\([^)]*\b" + re.escape(type_name) + r"\b[^)]*\)"  # parenthesized
        r")",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(source):
        return True

    # Also check multi-line parenthesized imports that span lines:
    # from module import (
    #     Foo,
    #     type_name,
    # )
    paren_pattern = re.compile(
        r"^from\s+\S+\s+import\s+\(([^)]*)\)",
        re.MULTILINE | re.DOTALL,
    )
    for m in paren_pattern.finditer(source):
        names_block = m.group(1)
        names = [n.strip().rstrip(",") for n in names_block.split(",")]
        names = [n.strip() for n in names if n.strip()]
        if type_name in names:
            return True

    return False


def needs_import(source: str, type_name: str) -> bool:
    """Return True if *type_name* needs an import added to *source*.

    Returns False for builtins and already-imported names.
    Returns False for names not in IMPORT_SOURCES (unknown types).
    """
    if type_name in BUILTIN_TYPES:
        return False
    if type_name not in IMPORT_SOURCES:
        return False
    return not _is_imported(source, type_name)


def detect_preferred_module(source: str, type_name: str) -> str:
    """Detect the preferred import module based on the file's existing style.

    If the file already uses ``from typing import ...``, prefer ``typing``.
    Otherwise use the default from IMPORT_SOURCES (``collections.abc``).
    """
    default = IMPORT_SOURCES.get(type_name, "collections.abc")

    # Check if file uses `from typing import ...` style
    if re.search(r"^from\s+typing\s+import\s+", source, re.MULTILINE):
        return "typing"

    # Check if file uses `from collections.abc import ...` style
    if re.search(r"^from\s+collections\.abc\s+import\s+", source, re.MULTILINE):
        return "collections.abc"

    return default


def find_last_import_line(lines: list[str]) -> int:
    """Return the 0-based index of the last import statement line.

    Handles multi-line parenthesized imports. Returns -1 if no imports found.
    """
    last_import = -1
    in_paren_import = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if in_paren_import:
            last_import = i
            if ")" in stripped:
                in_paren_import = False
            continue

        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import = i
            if "(" in stripped and ")" not in stripped:
                in_paren_import = True

    return last_import


def _find_existing_import_line(
    lines: list[str], module: str
) -> int | None:
    """Find a single-line ``from {module} import ...`` that can be extended.

    Returns the 0-based line index, or None if not found or if the import
    is multi-line (parenthesized).
    """
    pattern = re.compile(
        r"^from\s+" + re.escape(module) + r"\s+import\s+(?!\()"
    )
    for i, line in enumerate(lines):
        if pattern.match(line.rstrip()):
            return i
    return None


def add_import(
    source: str, type_name: str, module: str
) -> tuple[str, int | None]:
    """Add ``from {module} import {type_name}`` to *source*.

    Returns (new_source, inserted_line_number) where inserted_line_number is
    the 0-based line index of the NEW line, or None if the name was appended
    to an existing import line (no new line inserted, no line shift).
    """
    lines = source.splitlines(keepends=True)

    # Try to append to an existing `from {module} import ...` line
    existing = _find_existing_import_line(lines, module)
    if existing is not None:
        old_line = lines[existing]
        # Append before the newline
        stripped = old_line.rstrip("\n\r")
        new_line = stripped + ", " + type_name
        # Preserve original line ending
        ending = old_line[len(stripped):]
        lines[existing] = new_line + ending
        return "".join(lines), None

    # Insert a new import line after the last import
    last = find_last_import_line(lines)
    insert_at = last + 1 if last >= 0 else 0

    # Determine line ending style
    eol = "\n"
    if lines:
        for line in lines:
            if line.endswith("\r\n"):
                eol = "\r\n"
                break
            elif line.endswith("\n"):
                eol = "\n"
                break

    import_line = f"from {module} import {type_name}{eol}"
    lines.insert(insert_at, import_line)
    return "".join(lines), insert_at
