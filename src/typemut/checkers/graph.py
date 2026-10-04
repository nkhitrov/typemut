"""Project-internal import graph: which project files a set of files depends on."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final

import parso

from typemut.imports import ModuleImports

# File suffixes of a module: its source and its stub.
_SUFFIXES: Final = (".py", ".pyi")
# Files that make a directory a package.
_INIT_FILES: Final = tuple(f"__init__{suffix}" for suffix in _SUFFIXES)


class ImportGraph:
    """Follows the imports of project files to the project files they load.

    Module names are looked up from the root of the importing file's package,
    from every directory above it up to the project root, and from every
    top-level project directory that is not a package itself (``src``,
    ``lib``), so namespace packages (no ``__init__.py``) resolve and files
    outside a ``src`` layout (``tests``, scripts) reach the packages in it.
    A module is its ``.py`` file and its ``.pyi`` stub, either of which may
    be missing; it also loads the ``__init__`` of each of its parent
    packages. When in doubt a file counts as a dependency: an extra one only
    costs a re-run.
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
        top_roots = self._top_level_roots(project)
        seen: set[Path] = set()
        pending = [(project / file).resolve() for file in files]
        while pending:
            file = pending.pop()
            if file not in seen:
                seen.add(file)
                pending.extend(self._imported_files(file, project, top_roots))
        return {
            file.relative_to(project).as_posix() for file in seen if file.is_relative_to(project)
        }

    def _top_level_roots(self, project: Path) -> Iterable[Path]:
        """Top-level directories of *project* packages may live in (``src``).

        Every visible directory that is not a package itself.
        """
        try:
            children = sorted(project.iterdir())
        except OSError:
            return []
        return [
            child
            for child in children
            if child.is_dir()
            and not child.name.startswith(".")
            and not any((child / init).is_file() for init in _INIT_FILES)
        ]

    def _imported_files(
        self, file: Path, project: Path, top_roots: Iterable[Path]
    ) -> Iterable[Path]:
        """Project files the imports of *file* load."""
        try:
            source = file.read_text()
        except (OSError, UnicodeDecodeError):
            return []
        package = self._imports.package_of(file)
        modules = self._imports.imported_modules(parso.parse(source), package)
        roots = dict.fromkeys([*self._search_roots(file, package, project), *top_roots])
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
                directory.joinpath(*parts[:end], init)
                for end in range(1, len(parts))
                for init in _INIT_FILES
            ]
            base = directory.joinpath(*parts)
            modules = [base.parent / f"{base.name}{suffix}" for suffix in _SUFFIXES]
            candidates = [*packages, *modules, *(base / init for init in _INIT_FILES)]
            found.extend(candidate.resolve() for candidate in candidates if candidate.is_file())
        return found
