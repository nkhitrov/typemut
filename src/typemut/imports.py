"""Type origin registry and import injection for mutation targets.

When a mutation operator replaces a type with another (e.g. list -> Sequence),
the target type may not be imported in the file. This module provides:
- A central mapping of type names to their standard library modules
- :class:`ImportInjector` to detect existing imports and inject new ones
- :class:`ModuleImports` to map imported names to their qualified names
"""

from __future__ import annotations

import re
from collections.abc import Container, Iterable, Iterator, Mapping
from pathlib import Path

from parso.python.tree import BaseNode, ImportFrom, ImportName, Leaf, Module

# ---------------------------------------------------------------------------
# Type origin classification
# ---------------------------------------------------------------------------

# Python builtins — no import needed.
BUILTIN_TYPES: frozenset[str] = frozenset(
    {
        "list",
        "tuple",
        "set",
        "frozenset",
        "dict",
        "int",
        "str",
        "float",
        "bool",
        "bytes",
        "bytearray",
        "complex",
        "object",
        "type",
        "None",
        "memoryview",
    }
)

# Types available from collections.abc (preferred for Python 3.9+)
# and also re-exported by typing for backwards compatibility.
# Key = type name, value = default module to import from.
IMPORT_SOURCES: Mapping[str, str] = {
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

_IMPORT_LINE_RE = re.compile(r"^(?:from\s+[\w.]+\s+import\s|import\s+[\w.])")


class ImportInjector:
    """Adds the import a mutated annotation needs to a module's source.

    *sources* maps a type name to the module it is imported from by default,
    *builtins* are names that never need an import.
    """

    def __init__(
        self,
        sources: Mapping[str, str] = IMPORT_SOURCES,
        builtins: Container[str] = BUILTIN_TYPES,
    ) -> None:
        self._sources = sources
        self._builtins = builtins

    def resolve(
        self,
        source: str,
        mutated_annotation: str,
        required_import: str | None,
    ) -> tuple[str, int | None]:
        """Resolve and add the needed import for a mutation.

        Uses *required_import* from the mutation if provided, otherwise falls back
        to the default sources for standard library types.

        Returns (new_source, inserted_line) where inserted_line is the 0-based
        line index of the new import, or None if no new line was added.
        """
        type_name = self.type_name(mutated_annotation)

        # If the mutation provides an explicit import line, use it
        if required_import is not None:
            # Extract the name from the import line to check if already imported
            m = re.match(r"from\s+\S+\s+import\s+(\w+)", required_import.strip())
            if m:
                name = m.group(1)
                if self._is_imported(source, name):
                    return source, None
            return self.add_line(source, required_import)

        # Fallback to the default sources for known standard library types
        if self.needs_import(source, type_name):
            module = self.preferred_module(source, type_name)
            return self.add(source, type_name, module)

        return source, None

    def add_line(self, source: str, import_line: str) -> tuple[str, int | None]:
        """Add a raw import line (e.g. ``from pydantic import BaseModel``) to source.

        Parses *import_line* to extract module and name, then delegates to
        :meth:`add` for smart merging with existing imports.

        Returns (new_source, inserted_line_number) — same semantics as :meth:`add`.
        """
        m = re.match(r"from\s+(\S+)\s+import\s+(\w+)", import_line.strip())
        if m:
            module, name = m.group(1), m.group(2)
            return self.add(source, name, module)

        # Fallback: insert as-is after last import
        lines = source.splitlines(keepends=True)
        insert_at = self.last_import_line(lines) + 1
        lines.insert(insert_at, import_line.rstrip() + self._line_ending(lines))
        return "".join(lines), insert_at

    def add(self, source: str, type_name: str, module: str) -> tuple[str, int | None]:
        """Add ``from {module} import {type_name}`` to *source*.

        Returns (new_source, inserted_line_number) where inserted_line_number is
        the 0-based line index of the NEW line, or None if the name was appended
        to an existing import line (no new line inserted, no line shift).
        """
        lines = source.splitlines(keepends=True)

        # Try to append to an existing `from {module} import ...` line
        existing = self._find_existing_import_line(lines, module)
        if existing is not None:
            old_line = lines[existing]
            # Append before the newline
            stripped = old_line.rstrip("\n\r")
            new_line = stripped + ", " + type_name
            # Preserve original line ending
            ending = old_line[len(stripped) :]
            lines[existing] = new_line + ending
            return "".join(lines), None

        # Insert a new import line after the last import
        insert_at = self.last_import_line(lines) + 1
        lines.insert(insert_at, f"from {module} import {type_name}{self._line_ending(lines)}")
        return "".join(lines), insert_at

    def needs_import(self, source: str, type_name: str) -> bool:
        """Return True if *type_name* needs an import added to *source*.

        Returns False for builtins and already-imported names.
        Returns False for names without a default source (unknown types).
        """
        if type_name in self._builtins:
            return False
        if type_name not in self._sources:
            return False
        return not self._is_imported(source, type_name)

    def source_module(self, type_name: str) -> str | None:
        """The module *type_name* is imported from by default, if it is a known type."""
        return self._sources.get(type_name)

    def preferred_module(self, source: str, type_name: str) -> str:
        """Detect the preferred import module based on the file's existing style.

        If the file already uses ``from typing import ...``, prefer ``typing``.
        Otherwise use the default source (``collections.abc``).
        """
        default = self._sources.get(type_name, "collections.abc")

        # Check if file uses `from typing import ...` style
        if re.search(r"^from\s+typing\s+import\s+", source, re.MULTILINE):
            return "typing"

        # Check if file uses `from collections.abc import ...` style
        if re.search(r"^from\s+collections\.abc\s+import\s+", source, re.MULTILINE):
            return "collections.abc"

        return default

    def last_import_line(self, lines: Iterable[str]) -> int:
        """Return the 0-based index of the last import statement line.

        Only matches real import statements (not ``from`` in docstrings or
        comments). Handles multi-line parenthesized imports. Returns -1 if
        no imports found.
        """
        last_import = -1
        in_paren_import = False
        in_docstring = False
        docstring_quote = ""

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Track triple-quoted strings (docstrings)
            if not in_docstring:
                for q in ('"""', "'''"):
                    if q in stripped:
                        count = stripped.count(q)
                        if count == 1:
                            in_docstring = True
                            docstring_quote = q
                            break
                        # count >= 2 means open+close on same line — not in docstring
            else:
                if docstring_quote in stripped:
                    in_docstring = False
                continue

            if in_docstring:
                continue

            if in_paren_import:
                last_import = i
                if ")" in stripped:
                    in_paren_import = False
                continue

            # Only match lines at column 0 (module-level imports)
            if line and not line[0].isspace() and _IMPORT_LINE_RE.match(stripped):
                last_import = i
                if "(" in stripped and ")" not in stripped:
                    in_paren_import = True

        return last_import

    def _find_existing_import_line(self, lines: Iterable[str], module: str) -> int | None:
        """Find a single-line ``from {module} import ...`` that can be extended.

        Returns the 0-based line index, or None if not found or if the import
        is multi-line (parenthesized).
        """
        pattern = re.compile(r"^from\s+" + re.escape(module) + r"\s+import\s+(?!\()")
        for i, line in enumerate(lines):
            if pattern.match(line.rstrip()):
                return i
        return None

    def _is_imported(self, source: str, type_name: str) -> bool:
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

    @staticmethod
    def type_name(annotation: str) -> str:
        """Extract the root type name from an annotation string.

        >>> ImportInjector.type_name("Sequence[int]")
        'Sequence'
        >>> ImportInjector.type_name("Generator[int, None, None]")
        'Generator'
        >>> ImportInjector.type_name("int")
        'int'
        """
        bracket = annotation.find("[")
        if bracket == -1:
            return annotation.strip()
        return annotation[:bracket].strip()

    def _line_ending(self, lines: Iterable[str]) -> str:
        """The line ending of the first terminated line in *lines*, LF by default."""
        for line in lines:
            if line.endswith("\r\n"):
                return "\r\n"
            if line.endswith("\n"):
                return "\n"
        return "\n"


# ---------------------------------------------------------------------------
# Qualified names of imported types
# ---------------------------------------------------------------------------


class ModuleImports:
    """Maps the names a module's imports bind to their qualified names."""

    def package_of(self, file: Path) -> str:
        """Return the dotted package a file belongs to, e.g. ``app/x/models.py`` -> ``app.x``.

        The package root is the topmost directory still containing ``__init__.py``.
        Used to resolve relative imports.
        """
        parts: list[str] = []
        directory = file.parent
        while directory.name and (directory / "__init__.py").exists():
            parts.append(directory.name)
            directory = directory.parent
        return ".".join(reversed(parts))

    def names(self, tree: Module, package: str = "") -> dict[str, str]:
        """Map every name bound by an import in *tree* to its qualified name.

        ``from sqlalchemy.orm import Mapped as M`` -> ``{"M": "sqlalchemy.orm.Mapped"}``
        ``import sqlalchemy.orm as orm``           -> ``{"orm": "sqlalchemy.orm"}``
        ``import sqlalchemy.orm``                  -> ``{"sqlalchemy": "sqlalchemy"}``
        ``from .models import User`` (in ``app``)  -> ``{"User": "app.models.User"}``

        Imports anywhere in the module count (e.g. under ``if TYPE_CHECKING:``).
        Star imports bind nothing we can know statically and are skipped.
        """
        names: dict[str, str] = {}
        for imp in self._iter_imports(tree):
            defined_names = imp.get_defined_names()
            if not defined_names:
                continue  # star import
            prefix = self._relative_prefix(imp, package)
            for defined, path in zip(defined_names, imp.get_paths(), strict=True):
                if isinstance(imp, ImportName) and defined is path[0]:
                    # ``import a.b`` binds only ``a``
                    names[defined.value] = defined.value
                else:
                    names[defined.value] = prefix + ".".join(leaf.value for leaf in path)
        return names

    def imported_modules(self, tree: Module, package: str = "") -> set[str]:
        """Dotted names of the modules imports in *tree* may load.

        ``from app.models import User`` -> ``{"app.models", "app.models.User"}``
        (``User`` may itself be a module), ``import app.api as api`` ->
        ``{"app.api"}``, ``from . import *`` (in ``app``) -> ``{"app"}``.
        """
        modules: set[str] = set()
        for imp in self._iter_imports(tree):
            prefix = self._relative_prefix(imp, package)
            paths = (
                [leaf.value for leaf in imp.get_from_names()] if isinstance(imp, ImportFrom) else []
            )
            dotted_paths = [paths, *([leaf.value for leaf in path] for path in imp.get_paths())]
            modules.update((prefix + ".".join(path)).rstrip(".") for path in dotted_paths)
        modules.discard("")
        return modules

    def _iter_imports(self, node: BaseNode | Leaf) -> Iterator[ImportFrom | ImportName]:
        if isinstance(node, ImportFrom | ImportName):
            yield node
        elif isinstance(node, BaseNode):
            for child in node.children:
                yield from self._iter_imports(child)

    def _relative_prefix(self, imp: ImportFrom | ImportName, package: str) -> str:
        """Return the absolute package prefix for a relative ``from . import`` statement."""
        level = imp.level if isinstance(imp, ImportFrom) else 0
        if level == 0:
            return ""
        parts = package.split(".") if package else []
        base = parts[: len(parts) - (level - 1)]
        return "".join(f"{part}." for part in base)
