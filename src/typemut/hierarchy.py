"""Qualified names and base classes of the classes defined in a project.

Used by ``[typemut.ignore-classes]`` (see ``typemut.ignore``) to tell whether
an annotation is a field of a class that inherits from a configured one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Class, ClassOrFunc, Leaf, Module

from typemut.imports import ModuleImports
from typemut.nodes import NodeSource

# id(module tree) -> (module tree, {top-level name: qualified name})
_ScopeCache = dict[int, tuple[Module, dict[str, str]]]


class ClassNames(NodeSource):
    """Qualified names (``app.api.ItemResponse``) of classes and their bases."""

    def __init__(self, imports: ModuleImports | None = None) -> None:
        self._imports = imports or ModuleImports()
        self._scopes: _ScopeCache = {}

    def module_name(self, file: Path) -> str:
        """Dotted module name of a file: ``app/api/models.py`` -> ``app.api.models``."""
        package = self._imports.package_of(file)
        if file.stem == "__init__":
            return package
        return f"{package}.{file.stem}" if package else file.stem

    def enclosing_class(self, node: BaseNode | Leaf) -> Class | None:
        """The class whose body holds *node* directly (not inside one of its methods)."""
        parent = node.parent
        while parent is not None and not isinstance(parent, ClassOrFunc):
            parent = parent.parent
        return parent if isinstance(parent, Class) else None

    def qualified_name(self, classdef: Class, file: Path) -> str:
        """``module.Outer.Inner`` for a class nested in ``Outer`` in *file*'s module."""
        parts = [classdef.name.value]
        parent = classdef.parent
        while parent is not None:
            if isinstance(parent, ClassOrFunc):
                parts.append(parent.name.value)
            parent = parent.parent
        return ".".join(filter(None, [self.module_name(file), *reversed(parts)]))

    def bases(self, classdef: Class, file: Path) -> tuple[str, ...]:
        """Qualified names of the bases of a class, resolved through its module's imports.

        Imported bases get the name they are imported under (``pydantic.BaseModel``),
        classes of the same module the module's name; other names (builtins) stay
        as written. Keyword arguments (``metaclass=...``) are not bases.
        """
        arglist = classdef.get_super_arglist()
        if arglist is None:
            return ()
        items = arglist.children if arglist.type == "arglist" else [arglist]
        scope = self._scope(classdef.get_root_node(), file)
        dotted = (self._dotted_name(item) for item in items)
        return tuple(self._qualify(name, scope) for name in dotted if name is not None)

    # parso's children are untyped, so a narrower parameter type would pass mypy too.
    def _dotted_name(self, node: BaseNode | Leaf) -> str | None:  # pragma: no mutate
        """``orm.Base`` for ``orm.Base`` or ``orm.Base[T]``, None for anything else."""
        if isinstance(node, Leaf):
            return node.value if node.type == "name" else None
        return self._dotted_head(node)

    def _qualify(self, dotted: str, scope: Mapping[str, str]) -> str:
        """Resolve the head of *dotted* through *scope*; unknown names stay as written."""
        head, _, tail = dotted.partition(".")
        qualified = scope.get(head)
        if qualified is None:
            return dotted
        return f"{qualified}.{tail}" if tail else qualified

    def _scope(self, root: Module, file: Path) -> dict[str, str]:
        """Qualified names of the module's top-level classes and imported names."""
        cached = self._scopes.get(id(root))
        if cached is None or cached[0] is not root:
            classes = {
                classdef.name.value: self.qualified_name(classdef, file)
                for classdef in root.iter_classdefs()
            }
            imported = self._imports.names(root, self._imports.package_of(file))
            cached = (root, classes | imported)
            self._scopes[id(root)] = cached
        return cached[1]


@dataclass
class ClassHierarchy:
    """Bases of the project's classes, by qualified name."""

    # {qualified class name: qualified names of its bases}; only ever iterated,
    # so Sequence would pass mypy too.
    bases: dict[str, tuple[str, ...]] = field(default_factory=dict)  # pragma: no mutate

    # {name a project module binds by import: qualified name it imports},
    # e.g. {"app.api.BaseResponse": "app.api.base.BaseResponse"} for a re-export
    reexports: dict[str, str] = field(default_factory=dict)

    def lineage(self, name: str, bases: Iterable[str] = ()) -> set[str]:
        """*name*, its *bases* and all their known ancestors, under every name they have."""
        found: set[str] = set()
        pending = [name, *bases]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(self.bases.get(current, ()))
            reexported = self.reexports.get(current)
            if reexported is not None:
                pending.append(reexported)
        return found


class ClassHierarchyBuilder:
    """Builds the :class:`ClassHierarchy` of the classes defined in a set of files."""

    def __init__(
        self,
        names: ClassNames | None = None,
        imports: ModuleImports | None = None,
    ) -> None:
        self._names = names or ClassNames()
        self._imports = imports or ModuleImports()

    def build(self, files: Iterable[Path]) -> ClassHierarchy:
        """Hierarchy of the classes in *files*; unreadable files are skipped."""
        hierarchy = ClassHierarchy()
        for file in files:
            try:
                source = file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            self._add_module(hierarchy, parso.parse(source), file)
        return hierarchy

    def _add_module(self, hierarchy: ClassHierarchy, tree: Module, file: Path) -> None:
        module = self._names.module_name(file)
        imported = self._imports.names(tree, self._imports.package_of(file))
        hierarchy.reexports.update(
            (f"{module}.{local}", qualified) for local, qualified in imported.items()
        )
        for classdef in self._classdefs(tree):
            name = self._names.qualified_name(classdef, file)
            hierarchy.bases[name] = self._names.bases(classdef, file)

    # parso's children are untyped, so a narrower parameter type would pass mypy too.
    def _classdefs(self, node: BaseNode | Leaf) -> Iterable[Class]:  # pragma: no mutate
        if isinstance(node, Class):
            yield node
        if isinstance(node, BaseNode):
            for child in node.children:
                yield from self._classdefs(child)
