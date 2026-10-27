"""Abstract base for library plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Container, Iterable
from pathlib import Path
from typing import NamedTuple

from parso.python.tree import BaseNode, Function, Leaf, Name

from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.nodes import NodeSource
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry
from typemut.symbols import ScopeReader, SymbolResolver

SIGNATURE = frozenset((AnnotationContext.PARAMETER, AnnotationContext.RETURN))


class DecoratorReference(NamedTuple):
    """What a decorator refers to: ``@rpc.method()`` -> ``("rpc.method", called=True)``."""

    name: str
    called: bool


class Plugin(NodeSource, ABC):
    """Library-specific knowledge layered on top of the core operators.

    Core operators are library-agnostic. Libraries that wrap user types in
    their own generics (``Mapped[...]`` in SQLAlchemy, for example) give some
    of the core mutations a different meaning: a mutation can be invalid for
    the library at runtime, or have to be applied inside the wrapper.
    A plugin claims such annotations and decides which mutations they get.
    """

    name: str = ""

    def scan(self, files: Iterable[Path]) -> None:
        """Collect project-wide facts from all source *files* before any :meth:`find_mutations`.

        Called once per discovery. The default does nothing.
        """

    def operators(self) -> list[TypeMutationOperator]:
        """Return extra, library-specific operators run on every annotation."""
        return []

    @abstractmethod
    def find_mutations(
        self,
        annotation: AnnotationNode,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
    ) -> list[Mutation] | None:
        """Return the mutations for an annotation this plugin owns.

        Return None to leave the annotation to the core operators.
        """
        ...

    def _trailer_target(self, node: BaseNode | Leaf, bracket: str) -> tuple[str, BaseNode] | None:
        """For ``name[...]``/``a.name(...)`` return the name and the last trailer."""
        if not isinstance(node, BaseNode) or node.type not in {"atom_expr", "power"}:
            return None
        trailer = node.children[-1]
        if not isinstance(trailer, BaseNode) or trailer.type != "trailer":
            return None
        opening = trailer.children[0]
        if not isinstance(opening, Leaf) or opening.value != bracket:
            return None

        target = node.children[-2]
        if isinstance(target, BaseNode) and target.type == "trailer":
            # Attribute access: `.name`
            target = target.children[-1]
        if not isinstance(target, Leaf) or target.type != "name":
            return None
        return target.value, trailer


class HandlerPlugin(Plugin):
    """Skips the signatures of handlers: functions a framework calls, not Python code.

    No caller means the type checker has nothing to check a mutated signature
    against, so every mutation of a handler's parameter and return annotations
    survives. Annotations inside the handler's body are mutated as usual.
    Subclasses decide which functions are handlers; names are resolved
    statically with :class:`SymbolResolver`, never by variable names.
    """

    def __init__(
        self, resolver: SymbolResolver | None = None, scopes: ScopeReader | None = None
    ) -> None:
        self._scopes = scopes or ScopeReader()
        self._resolver = resolver or SymbolResolver(scopes=self._scopes)

    def find_mutations(
        self,
        annotation: AnnotationNode,
        # Unused: the signature mirrors Plugin.find_mutations.
        operators: Collection[TypeMutationOperator],  # pragma: no mutate
        registry: Registry,
    ) -> list[Mutation] | None:
        """No mutations for skipped signature annotations; leave the others to the core."""
        if annotation.context not in SIGNATURE:
            return None
        # Parameter and return annotations only occur in function signatures.
        funcdef = annotation.node.search_ancestor("funcdef")
        assert isinstance(funcdef, Function)
        if annotation.context in self._skipped(funcdef, annotation.file):
            return []
        return None

    def _skipped(
        self, funcdef: Function, file: Path
    ) -> Container[AnnotationContext]:  # pragma: no mutate (membership-tested)
        """Which signature annotations of *funcdef* get no mutations: all of a handler's."""
        return SIGNATURE if self._is_handler(funcdef, file) else frozenset()

    @abstractmethod
    def _is_handler(
        self, funcdef: Function, file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether the framework calls *funcdef*, defined in *file*."""
        ...

    def _is_method_of(
        self, funcdef: Function, file: Path, classes: Container[str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether *funcdef* is a method of a class inheriting from one of *classes*.

        Inheritance is resolved statically, through project classes in any module.
        """
        scope = funcdef.search_ancestor("classdef", "funcdef")
        if scope is None or scope.type != "classdef":
            return False
        bases = (self._resolver.qualify(base, file) for base in self._scopes.bases(scope))
        return any(
            base is not None and self._resolver.inherits_from(base, classes, file) for base in bases
        )

    def _decorators(self, funcdef: Function) -> Iterable[BaseNode]:
        """Decorators of a function."""
        decorated = funcdef.parent
        if decorated is not None and decorated.type == "async_funcdef":
            decorated = decorated.parent
        if decorated is None or decorated.type != "decorated":
            return []
        decorators = decorated.children[0]
        if decorators.type == "decorator":
            return [decorators]
        return list(decorators.children)

    def _decorator_reference(self, decorator: BaseNode) -> DecoratorReference | None:
        """Dotted name a decorator refers to, None unless it is ``@name``/``@a.b[(...)]``."""
        expression = decorator.children[1]
        if isinstance(expression, Name):
            return DecoratorReference(expression.value, called=False)
        if expression.type not in {"atom_expr", "power"}:
            return None
        nodes = expression.children
        called = self._trailer_target(expression, "(") is not None
        name = self._scopes.dotted_name(nodes[:-1] if called else nodes)
        return None if name is None else DecoratorReference(name, called)

    def _is_instance_member(
        self, dotted: str, node: BaseNode | Leaf, file: Path, names: Container[str]
    ) -> bool:
        """Whether *dotted* is ``<instance>.<member>`` and ``<its class>.<member>`` is in *names*."""
        return self._resolver.instance_member(dotted, node, file, names)
