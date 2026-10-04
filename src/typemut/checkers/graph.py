"""Project-internal import graph: which project files a set of files depends on."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import parso

from typemut.imports import ModuleImports
from typemut.symbols import SymbolResolver


class ImportGraph:
    """Follows the imports of project files to the project files they load."""

    def __init__(
        self,
        imports: ModuleImports | None = None,
        resolver: SymbolResolver | None = None,
    ) -> None:
        self._imports = imports or ModuleImports()
        self._resolver = resolver or SymbolResolver(self._imports)

    def closure(self, files: Iterable[str], root: Path) -> set[str]:
        """*files* and every project file they import, directly or not.

        Paths are relative to *root*, in and out. Imports of modules outside
        the project (the standard library, installed packages) are not
        followed; unreadable files are kept but import nothing.
        """
        project = root.resolve()
        seen: set[Path] = set()
        pending = [(project / file).resolve() for file in files]
        while pending:
            file = pending.pop()
            if file not in seen:
                seen.add(file)
                pending.extend(self._imported_files(file))
        return {
            file.relative_to(project).as_posix() for file in seen if file.is_relative_to(project)
        }

    def _imported_files(self, file: Path) -> list[Path]:
        """Project files the imports of *file* load."""
        try:
            source = file.read_text()
        except (OSError, UnicodeDecodeError):
            return []
        modules = self._imports.imported_modules(
            parso.parse(source), self._imports.package_of(file)
        )
        found = (self._resolver.module_file(module, file) for module in modules)
        return [path for path in found if path is not None]
