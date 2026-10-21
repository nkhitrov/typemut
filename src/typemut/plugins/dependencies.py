"""Dependency providers: project functions a DI framework calls through markers.

FastAPI calls ``f`` for ``Depends(f)`` and passes its result on;
``Annotated[int, Depends(f)]`` never relates ``int`` to the return type of
``f``. If nothing else in the project uses ``f``, the type checker has no
caller to check its mutated return type against, and every such mutation
survives. :class:`DependencyProviders` finds these providers project-wide.

A provider is what a marker call (``Depends(f)``, ``Security(f, scopes=...)``,
``Depends(dependency=f)``) refers to, anywhere in the project: in a default
value, inside ``Annotated[...]``, in ``dependencies=[...]``, in a type alias.
The keys and values of an override mapping (``app.dependency_overrides[f] = g``)
are providers as well. For a function ``f`` the framework calls ``f``; for an
instance ``checker = Checker(...)`` it calls ``Checker.__call__``.

A provider counts only while the project uses it through markers alone. Any
other reference (a direct call, ``f.cache_clear()``, ``checker("q")``) gives
the type checker a caller. Names are resolved statically through imports and
re-exports (see ``typemut.symbols``).
"""

from __future__ import annotations

from collections.abc import Container, Iterable
from pathlib import Path
from typing import Final

from parso.python.tree import BaseNode, Function, Leaf, Name

from typemut.symbols import ScopeReader, SymbolResolver

NO_OVERRIDES: Final = frozenset[str]()


class DependencyProviders:
    """Project functions and ``__call__`` methods a framework calls through dependency *markers*.

    *markers* are qualified names of marker callables (``fastapi.Depends``);
    *overrides* are qualified ``Class.attribute`` names of override mappings
    (``fastapi.FastAPI.dependency_overrides``). :meth:`scan` reads the project
    before :meth:`is_provider` answers.
    """

    def __init__(
        self,
        markers: Container[str],
        overrides: Container[str] = NO_OVERRIDES,
        resolver: SymbolResolver | None = None,
        scopes: ScopeReader | None = None,
    ) -> None:
        self._markers = markers
        self._overrides = overrides
        self._scopes = scopes or ScopeReader()
        self._resolver = resolver or SymbolResolver(scopes=self._scopes)
        # {provider (``mod.f``, ``mod.Checker.__call__``): names it is used by}
        self._providers: dict[str, set[str]] = {}
        # Project bindings referenced outside marker arguments.
        self._referenced: set[str] = set()

    def scan(self, files: Iterable[Path]) -> None:
        """Find the providers in *files* and every other use of project names."""
        self._providers.clear()
        self._referenced.clear()
        for file in files:
            path = file.resolve()
            tree = self._resolver.tree(path)
            if tree is not None:
                self._scan_module(tree, path)

    def is_provider(
        self, funcdef: Function, file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether the framework is the only caller of *funcdef*, defined in *file*."""
        key = self._key(funcdef, file.resolve())
        names = None if key is None else self._providers.get(key)
        return names is not None and names.isdisjoint(self._referenced)

    def _key(self, funcdef: Function, file: Path) -> str | None:
        """``mod.f`` for a module function, ``mod.Checker.__call__`` for a
        ``__call__`` method of a module class; None for other functions."""
        name = funcdef.name.value
        scope = funcdef.search_ancestor("classdef", "funcdef")
        if scope is None:
            return self._resolver.qualify(name, file)
        if scope.type != "classdef" or name != "__call__":
            return None
        if scope.search_ancestor("classdef", "funcdef") is not None:
            return None
        class_name = self._resolver.qualify(scope.children[1].value, file)
        return None if class_name is None else f"{class_name}.__call__"

    def _scan_module(self, tree: BaseNode, file: Path) -> None:
        arguments: set[int] = set()
        for node in self._walk(tree):
            for target in self._dependency_targets(node, file):
                arguments.update(id(leaf) for leaf in self._leaves(target))
                self._add_provider(target, file)
        for leaf in self._leaves(tree):
            if isinstance(leaf, Name) and id(leaf) not in arguments:
                self._add_reference(leaf, file)

    def _dependency_targets(self, node: BaseNode, file: Path) -> Iterable[BaseNode | Leaf]:
        """What a marker call or an override assignment at *node* registers."""
        if node.type in {"atom_expr", "power"}:
            target = self._marker_target(node, file)
            return [] if target is None else [target]
        if node.type == "expr_stmt":
            return self._override_targets(node, file)
        return []

    def _marker_target(self, node: BaseNode, file: Path) -> BaseNode | Leaf | None:
        """``f`` for ``Depends(f)``/``Depends(dependency=f)``, None for ``Depends()``."""
        call = node.children[-1]
        if call.type != "trailer" or call.children[0].value != "(":
            return None
        callee = self._scopes.dotted_name(node.children[:-1])
        if callee is None or self._resolver.qualify(callee, file) not in self._markers:
            return None
        return self._dependency_argument(call)

    def _dependency_argument(self, call: BaseNode) -> BaseNode | Leaf | None:
        """The first positional argument of a call, or its ``dependency=`` keyword."""
        if len(call.children) == 2:
            return None
        arguments = call.children[1]
        items: Iterable[BaseNode | Leaf] = (
            arguments.children[::2] if arguments.type == "arglist" else [arguments]
        )
        for item in items:
            if not isinstance(item, BaseNode) or item.type != "argument":
                return item
            keyword, value = item.children[0], item.children[-1]
            if isinstance(keyword, Name) and keyword.value == "dependency":
                assert isinstance(value, (BaseNode, Leaf))
                return value
        return None

    def _override_targets(self, stmt: BaseNode, file: Path) -> list[BaseNode | Leaf]:
        """Key and value of ``<app>.dependency_overrides[key] = value``."""
        target, operator = stmt.children[0], stmt.children[1]
        if len(stmt.children) != 3 or operator.type != "operator" or operator.value != "=":
            return []
        if target.type not in {"atom_expr", "power"}:
            return []
        subscript = target.children[-1]
        if subscript.type != "trailer" or subscript.children[0].value != "[":
            return []
        mapping = self._scopes.dotted_name(target.children[:-1])
        if mapping is None or not self._resolver.instance_member(
            mapping, stmt, file, self._overrides
        ):
            return []
        return [subscript.children[1], stmt.children[2]]

    def _add_provider(self, target: BaseNode | Leaf, file: Path) -> None:
        """Record what *target* (``f``, ``checker``) makes the framework call."""
        dotted = self._dotted(target)
        if dotted is None:
            return
        name = self._definition(dotted, file)
        if name is None:
            return
        class_name = self._resolver.instance_class(dotted, target, file)
        if class_name is None:
            provider: str | None = name
        else:
            definition = self._resolver.definition(class_name, file)
            provider = None if definition is None else f"{definition}.__call__"
        if provider is not None:
            self._providers.setdefault(provider, set()).add(name)

    def _add_reference(self, leaf: Name, file: Path) -> None:
        """Record the project bindings a name (``f``, ``deps.f``) refers to outside markers."""
        for dotted in self._scopes.references(leaf):
            name = self._definition(dotted, file)
            if name is not None:
                self._referenced.add(name)

    def _definition(self, dotted: str, file: Path) -> str | None:
        """The project binding *dotted* refers to at module level of *file*."""
        qualified = self._resolver.qualify(dotted, file)
        return None if qualified is None else self._resolver.definition(qualified, file)

    def _dotted(self, node: BaseNode | Leaf) -> str | None:
        """``f`` / ``deps.f`` for a name or an attribute chain, else None."""
        if isinstance(node, Name):
            return node.value
        if isinstance(node, BaseNode) and node.type in {"atom_expr", "power"}:
            return self._scopes.dotted_name(node.children)
        return None

    def _walk(self, node: BaseNode) -> Iterable[BaseNode]:
        yield node
        for child in node.children:
            if isinstance(child, BaseNode):
                yield from self._walk(child)

    def _leaves(self, node: BaseNode | Leaf) -> Iterable[Leaf]:
        if isinstance(node, Leaf):
            yield node
            return
        for child in node.children:
            yield from self._leaves(child)
