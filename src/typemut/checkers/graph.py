"""Project-internal import graph: which project files a set of files depends on."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import parso

from typemut.imports import ModuleImports


class ImportGraph:
    """Follows the imports of project files to the project files they load.

    Module names are looked up from the root of the importing file's package
    and from every directory above it up to the project root, so namespace
    packages (no ``__init__.py``) and ``src`` layouts resolve; a module also
    loads the ``__init__.py`` of each of its parent packages. When in doubt a
    file counts as a dependency: an extra one only costs a re-run.
    """

    def __init__(self, imports: ModuleImports | None = None) -> None:
        self._imports = imports or ModuleImports()

    def closure(self, files: Iterable[str], root: Path) -> Iterable[str]:
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
                pending.extend(self._imported_files(file, project))
        return {
            file.relative_to(project).as_posix() for file in seen if file.is_relative_to(project)
        }

    def _imported_files(self, file: Path, project: Path) -> Iterable[Path]:
        """Project files the imports of *file* load."""
        try:
            source = file.read_text()
        except (OSError, UnicodeDecodeError):
            return []
        package = self._imports.package_of(file)
        modules = self._imports.imported_modules(parso.parse(source), package)
        roots = self._search_roots(file, package, project)
        return [path for module in modules for path in self._module_files(module, roots)]

    def _search_roots(self, file: Path, package: str, project: Path) -> Iterable[Path]:
        """Directories absolute imports in *file* may resolve from, inside *project*."""
        start = file.parent
        for _ in package.split(".") if package else ():
            start = start.parent
        return [
            directory for directory in (start, *start.parents) if directory.is_relative_to(project)
        ]

    def _module_files(self, module: str, roots: Iterable[Path]) -> Iterable[Path]:
        """Existing files of *module* and of its parent packages under any of *roots*."""
        parts = module.split(".")
        found: list[Path] = []
        for directory in roots:
            packages = [
                directory.joinpath(*parts[:end], "__init__.py") for end in range(1, len(parts))
            ]
            base = directory.joinpath(*parts)
            candidates = [*packages, base.parent / f"{base.name}.py", base / "__init__.py"]
            found.extend(candidate.resolve() for candidate in candidates if candidate.is_file())
        return found
