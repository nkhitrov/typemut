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

import parso
from parso.python.tree import BaseNode, Class, Function, ImportFrom, ImportName, Leaf, Module
from parso.tree import NodeOrLeaf
from parso.utils import split_lines

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


class ImportStatements:
    """Reads import statements and module-level bindings from parso trees."""

    def single_from_import(self, import_line: str) -> tuple[str, str] | None:
        """``(module, name)`` of a plain absolute ``from {module} import {name}`` line."""
        imports = list(self.module_imports(parso.parse(import_line)))
        if len(imports) != 1 or not isinstance(imports[0], ImportFrom):
            return None
        imp = imports[0]
        paths = imp.get_paths()
        names = imp.get_defined_names()
        if imp.level or len(names) != 1 or names[0] is not paths[0][-1]:
            return None  # relative, star, several names or an alias
        return self.dotted(imp.get_from_names()), names[0].value

    def find_from_import(self, tree: Module, module: str) -> ImportFrom | None:
        """The first module-level ``from {module} import <names>`` a name can join."""
        for imp in self.module_imports(tree):
            if (
                isinstance(imp, ImportFrom)
                and not imp.level
                and not imp.is_star_import()
                and self.dotted(imp.get_from_names()) == module
            ):
                return imp
        return None

    def module_imports(self, tree: Module) -> Iterable[ImportFrom | ImportName]:
        """Import statements at the top level of *tree*, in source order.

        parso drops the ``simple_stmt`` wrapper of a lone statement without a
        newline (``import os`` at the end of a file), so both shapes count.
        """
        for stmt in tree.children:
            children = stmt.children if stmt.type == "simple_stmt" else [stmt]
            yield from (child for child in children if isinstance(child, ImportFrom | ImportName))

    def last_imported(self, imp: ImportFrom) -> NodeOrLeaf:
        """The last ``name`` / ``name as alias`` node a from-import lists."""
        names = imp.children[-1]
        if names.type == "operator":  # closing parenthesis
            names = imp.children[-2]
        if names.type == "import_as_names":
            items = [child for child in names.children if child.type != "operator"]
            return items[-1]
        return names

    def bound_names(self, node: NodeOrLeaf) -> set[str]:
        """Names bound at module level by imports and class definitions.

        Descends into ``if``/``try``/``with`` blocks (e.g. ``if TYPE_CHECKING:``)
        but not into function or class bodies. ``import a.b`` binds ``a`` and
        is recorded as ``a.b`` too, so it doesn't count as ``import a.c``.
        """
        if isinstance(node, Class):
            return {node.name.value}
        if isinstance(node, ImportName):
            return {name.value for name in node.get_defined_names()} | {
                self.dotted(path) for path in node.get_paths()
            }
        if isinstance(node, ImportFrom):
            return {name.value for name in node.get_defined_names()}
        if isinstance(node, Function) or not isinstance(node, BaseNode):
            return set()
        return {name for child in node.children for name in self.bound_names(child)}

    def dotted(self, names: Iterable[Leaf]) -> str:
        """``a.b.c`` for the name leaves ``a``, ``b``, ``c``."""
        return ".".join(name.value for name in names)


class ImportInjector:
    """Adds the import a mutated annotation needs to a module's source.

    *sources* maps a type name to the module it is imported from by default,
    *builtins* are names that never need an import, *statements* reads the
    imports of a source.

    Sources are read with parso, so comments, docstrings, aliases, parentheses
    and line continuations in existing imports are handled by the grammar.
    A name is merged only into a module-level ``from {module} import ...``
    statement; otherwise a new import line is added after the last
    module-level import. A name counts as imported when any module-level
    statement binds it, including imports under ``if TYPE_CHECKING:``.
    """

    def __init__(
        self,
        sources: Mapping[str, str] = IMPORT_SOURCES,
        builtins: Container[str] = BUILTIN_TYPES,
        statements: ImportStatements | None = None,
    ) -> None:
        self._sources = sources
        self._builtins = builtins
        self._statements = statements or ImportStatements()

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
        if required_import is not None:
            names = self._statements.bound_names(parso.parse(required_import.strip()))
            if names and names <= self._statements.bound_names(parso.parse(source)):
                return source, None
            return self.add_line(source, required_import)

        type_name = self.type_name(mutated_annotation)
        if self.needs_import(source, type_name):
            module = self.preferred_module(source, type_name)
            return self.add(source, type_name, module)

        return source, None

    def add_line(self, source: str, import_line: str) -> tuple[str, int | None]:
        """Add a raw import line (e.g. ``from pydantic import BaseModel``) to source.

        A ``from {module} import {name}`` line is merged into an existing
        import of *module* by :meth:`add`; any other line is inserted as-is
        after the last import.

        Returns (new_source, inserted_line_number) — same semantics as :meth:`add`.
        """
        imported = self._statements.single_from_import(import_line.strip())
        if imported is not None:
            return self.add(source, imported[1], imported[0])
        return self._insert_line(source, import_line.strip())

    def add(self, source: str, type_name: str, module: str) -> tuple[str, int | None]:
        """Add ``from {module} import {type_name}`` to *source*.

        Returns (new_source, inserted_line_number) where inserted_line_number is
        the 0-based line index of the NEW line, or None if the name was appended
        to an existing import (or already imported there): no line shift.
        """
        tree = parso.parse(source)
        existing = self._statements.find_from_import(tree, module)
        if existing is None:
            return self._insert_line(source, f"from {module} import {type_name}")
        if type_name in {name.value for name in existing.get_defined_names()}:
            return source, None
        end = self._statements.last_imported(existing).end_pos
        return self._insert_at(source, end, f", {type_name}"), None

    def needs_import(self, source: str, type_name: str) -> bool:
        """Return True if *type_name* needs an import added to *source*.

        Returns False for builtins and already-imported names.
        Returns False for names without a default source (unknown types).
        """
        if type_name in self._builtins:
            return False
        if type_name not in self._sources:
            return False
        return type_name not in self._statements.bound_names(parso.parse(source))

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
        """Return the 0-based index of the last line of the last module-level import.

        Imports in docstrings, comments, functions or ``if`` blocks don't count;
        multi-line imports end at their last line. Returns -1 if there are none.
        """
        imports = list(self._statements.module_imports(parso.parse("".join(lines))))
        if not imports:
            return -1
        return imports[-1].end_pos[0] - 1

    def _insert_line(self, source: str, import_line: str) -> tuple[str, int | None]:
        """Insert *import_line* after the last module-level import of *source*."""
        lines = source.splitlines(keepends=True)
        insert_at = self.last_import_line(lines) + 1
        lines.insert(insert_at, import_line + self._line_ending(lines))
        return "".join(lines), insert_at

    def _insert_at(self, source: str, position: tuple[int, int], text: str) -> str:
        """*source* with *text* inserted at a parso ``(line, column)`` position."""
        lines = split_lines(source, keepends=True)
        line, column = position
        lines[line - 1] = lines[line - 1][:column] + text + lines[line - 1][column:]
        return "".join(lines)

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

        The package root is the topmost directory still containing ``__init__.py``
        (or a ``__init__.pyi`` stub). Used to resolve relative imports.
        """
        parts: list[str] = []
        directory = file.parent
        while directory.name and any(
            (directory / init).exists() for init in ("__init__.py", "__init__.pyi")
        ):
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
