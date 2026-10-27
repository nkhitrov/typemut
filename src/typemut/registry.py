"""Build class hierarchy from source files."""

from __future__ import annotations

import builtins
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Class, Leaf, Module

from typemut.hierarchy import ClassNames
from typemut.imports import ModuleImports
from typemut.nodes import NodeSource


@dataclass(frozen=True)
class ClassBase:
    """The first base of a project class."""

    # Qualified name (``pydantic.BaseModel``), or the name as written when it
    # is neither defined nor imported by the class's module (``str``, an alias).
    name: str
    # Written with type arguments: ``class Child(Base[T])``.
    subscripted: bool = False


@dataclass(frozen=True)
class Widening:
    """The base class to widen a class to, as it can be written in a given file."""

    # The base's name in that file, e.g. ``BaseModel``.
    name: str
    # The base's qualified name, e.g. ``pydantic.BaseModel``.
    qualified: str
    # Import line bringing *name* into the file, None if it is already in scope.
    required_import: str | None = None
    # The base is written with type arguments in the class definition.
    subscripted: bool = False  # pragma: no mutate (truth-tested)


@dataclass
class Registry:
    """Stores the class hierarchy of a project's modules, by qualified name."""

    # {qualified class name: its first base}
    bases: dict[str, ClassBase] = field(default_factory=dict)

    # {qualified class name: defined unconditionally at module level, so importable}
    classes: dict[str, bool] = field(default_factory=dict)

    # Dotted names of the project's modules.
    modules: set[str] = field(default_factory=set)

    # {name a project module binds by import: qualified name it imports},
    # e.g. {"app.Cat": "app.models.Cat"} for a re-export.
    reexports: dict[str, str] = field(default_factory=dict)

    # {file: {top-level name: qualified name}} for the classes a file defines
    # and the names it imports.
    scopes: dict[Path, Mapping[str, str]] = field(default_factory=dict)

    # The file whose names :meth:`widening` resolves, see :meth:`in_file`.
    file: Path | None = None

    def in_file(self, file: Path) -> Registry:
        """This registry, resolving the names written in *file*."""
        return replace(self, file=file)

    def widening(self, name: str) -> Widening | None:
        """The base to widen the class *name* (as written in the file) to.

        None when *name* is not a project class with a base, or when the base
        cannot be written in the file: it is not importable (an alias, a
        conditional or nested definition) or its name is taken by something else.
        """
        scope = self._scope()
        qualified = scope.get(name)
        if qualified is None:
            return None
        base = self.bases.get(self._canonical(qualified))
        if base is None:
            return None
        target = self._canonical(base.name)
        local = self._written_name(target, scope)
        if local is not None:
            return Widening(name=local, qualified=target, subscripted=base.subscripted)
        module, _, short = target.rpartition(".")
        if short in scope or not self._importable(target, module):
            return None
        required_import = f"from {module} import {short}" if module else None
        return Widening(short, target, required_import, base.subscripted)

    def _scope(self) -> Mapping[str, str]:
        if self.file is None:
            return {}
        return self.scopes.get(self.file, {})

    def _written_name(self, qualified: str, scope: Mapping[str, str]) -> str | None:
        """How *qualified* is written with the names in *scope*: ``Base``, ``models.Base``."""
        for local, bound in scope.items():
            if self._canonical(bound) == qualified:
                return local
        for local, bound in scope.items():
            if qualified.startswith(f"{bound}."):
                return local + qualified[len(bound) :]
        return None

    def _canonical(self, name: str) -> str:
        """*name* with re-exports followed to the name of the definition."""
        seen: set[str] = set()
        while name in self.reexports and name not in seen:
            seen.add(name)
            name = self.reexports[name]
        return name

    def _importable(self, qualified: str, module: str) -> bool:  # pragma: no mutate (truth-tested)
        """Whether ``from module import name`` brings the *qualified* name in."""
        if not module:
            # Builtins need no import (unless the file binds them to something else).
            return hasattr(builtins, qualified)
        if qualified in self.classes:
            return self.classes[qualified]
        # A project module's other names are aliases or variables, not classes.
        return module not in self.modules


class RegistryBuilder(NodeSource):
    """Builds a :class:`Registry` from the class definitions in a set of files.

    *imports* resolves imported names (and the package of each file) to
    qualified names, *names* gives the qualified names of classes.
    """

    def __init__(
        self, imports: ModuleImports | None = None, names: ClassNames | None = None
    ) -> None:
        self._imports = imports or ModuleImports()
        self._names = names or ClassNames(self._imports)

    def build(self, files: Iterable[Path]) -> Registry:
        """Registry of the classes defined in *files*; unreadable files are skipped."""
        reg = Registry()
        for f in files:
            try:
                source = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            self._add_module(reg, parso.parse(source), f)
        return reg

    def _add_module(self, reg: Registry, tree: Module, file: Path) -> None:
        module = self._names.module_name(file)
        reg.modules.add(module)
        scope = self._module_scope(tree, file)
        reg.scopes[file] = scope
        reg.reexports.update((f"{module}.{local}", qualified) for local, qualified in scope.items())
        for classdef in self._classdefs(tree):
            name = self._names.qualified_name(classdef, file)
            reg.classes[name] = self._is_unconditional(classdef, tree)
            base = self._first_base(classdef, scope)
            if base is not None:
                reg.bases[name] = base

    def _module_scope(self, tree: Module, file: Path) -> Mapping[str, str]:
        """{name: qualified name} of the module-level classes and imports of *tree*.

        Imports and classes inside module-level ``try``/``if`` blocks count;
        those inside function or class bodies do not. The first binding of a
        name wins, so ``try:`` imports take precedence over ``except`` fallbacks.
        """
        package = self._imports.package_of(file)
        scope: dict[str, str] = {}
        for imp in tree.iter_imports():
            for name, qualified in self._imports.bindings(imp, package):
                scope.setdefault(name, qualified)
        for classdef in tree.iter_classdefs():
            scope.setdefault(classdef.name.value, self._names.qualified_name(classdef, file))
        return scope

    def _is_unconditional(self, classdef: Class, tree: Module) -> bool:
        """Whether *classdef* is a statement of the module itself (decorated or not)."""
        parent = classdef.parent
        if parent is not None and parent.type == "decorated":
            parent = parent.parent
        return parent is tree

    def _first_base(self, classdef: Class, scope: Mapping[str, str]) -> ClassBase | None:
        """The first base of a class written as a (dotted) name, maybe subscripted."""
        arglist = classdef.get_super_arglist()
        if arglist is None:
            return None
        items = arglist.children[::2] if arglist.type == "arglist" else [arglist]
        first = items[0]
        if isinstance(first, Leaf):
            return ClassBase(self._qualify(first.value, scope)) if first.type == "name" else None
        dotted = self._dotted_head(first)
        trailers = first.children[1:]
        names = trailers[: dotted.count(".")] if dotted is not None else trailers
        subscript = trailers[len(names) :]
        if dotted is None or len(subscript) > 1:
            return None
        if any(trailer.get_first_leaf().value != "[" for trailer in subscript):
            return None
        return ClassBase(self._qualify(dotted, scope), subscripted=bool(subscript))

    def _qualify(self, dotted: str, scope: Mapping[str, str]) -> str:
        """Resolve the head of *dotted* through *scope*; unknown names stay as written."""
        head, _, tail = dotted.partition(".")
        qualified = scope.get(head)
        if qualified is None:
            return dotted
        return f"{qualified}.{tail}" if tail else qualified

    # parso's children are untyped, so a narrower parameter type would pass mypy too.
    def _classdefs(self, node: BaseNode | Leaf) -> Iterable[Class]:  # pragma: no mutate
        if isinstance(node, Class):
            yield node
        if isinstance(node, BaseNode):
            for child in node.children:
                yield from self._classdefs(child)
