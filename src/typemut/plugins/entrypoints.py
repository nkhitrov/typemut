"""Entrypoints: skip the signatures of handlers that frameworks call, configured by name.

The generic counterpart of the ``fastapi`` plugin for any framework that
registers handlers (in-house RPC layers, message consumers, task queues)::

    [typemut.entrypoints]
    decorators = ["mylib.rpc.*.method", "faststream.*.subscriber"]
    base-classes = ["mylib.rpc.Endpoint"]
    parameter-types = ["mylib.rpc.Dependency"]

Patterns are ``fnmatch`` globs (``*`` also matches dots) matched against
qualified names, i.e. the name a class or function is imported under
(``mylib.rpc.Router``), resolved through imports and project modules
(see ``typemut.symbols``). A function is a handler when:

- **decorators**: one of its decorators (``@x``, ``@x.y``, ``@x.y(...)``)
  refers to a matching name. The decorator ``@rpc.method(...)`` matches as
  the qualified name of ``rpc.method`` itself, and, when ``rpc`` is an
  instance (``rpc = Router()``), as ``<class>.method`` for its class and
  every base class of it: ``mylib.rpc.Router.method``.
- **base-classes**: it is a method of a class that inherits from a matching
  class, directly or through project classes in any module.
- **parameter-types**: the annotation of one of its parameters references a
  matching name anywhere (``Dependency[Service]``,
  ``Annotated[Service, Inject]``), resolved like decorators:
  ``rpc.Dependency`` with ``rpc = Router()`` is ``mylib.rpc.Router.Dependency``.

Only parameter and return annotations of a handler are skipped; annotations
in its body are mutated as usual.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Sequence
from pathlib import Path

from parso.python.tree import BaseNode, Function, Leaf, Name

from typemut.config import EntrypointsConfig
from typemut.plugins.base import HandlerPlugin
from typemut.symbols import NamePatterns, ScopeReader, SymbolResolver


class EntrypointsPlugin(HandlerPlugin):
    name = "entrypoints"

    def __init__(
        self,
        config: EntrypointsConfig | None = None,
        resolver: SymbolResolver | None = None,
        scopes: ScopeReader | None = None,
    ) -> None:
        super().__init__(resolver, scopes)
        config = config or EntrypointsConfig()
        self._decorator_names = NamePatterns(config.decorators)
        self._base_classes = NamePatterns(config.base_classes)
        self._parameter_types = NamePatterns(config.parameter_types)

    def configured(self) -> bool:  # pragma: no mutate (truth-tested)
        """Whether any pattern is configured."""
        return bool(self._decorator_names or self._base_classes or self._parameter_types)

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        return (
            self._has_decorator(funcdef, file)
            or self._is_endpoint_method(funcdef, file)
            or self._has_parameter_type(funcdef, file)
        )

    def _has_decorator(
        self, funcdef: Function, file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        if not self._decorator_names:
            return False
        for decorator in self._decorators(funcdef):
            reference = self._decorator_reference(decorator)
            if reference is not None and self._refers_to(
                reference.name, decorator, file, self._decorator_names
            ):
                return True
        return False

    def _is_endpoint_method(
        self, funcdef: Function, file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether *funcdef* is a method of a class inheriting from a configured base class."""
        if not self._base_classes:
            return False
        return self._is_method_of(funcdef, file, self._base_classes)

    def _has_parameter_type(self, funcdef: Function, file: Path) -> bool:
        if not self._parameter_types:
            return False
        return any(
            self._refers_to(dotted, annotation, file, self._parameter_types)
            for annotation in self._scopes.parameter_annotations(funcdef)
            for dotted in self._references(annotation)
        )

    def _refers_to(
        self, dotted: str, node: BaseNode | Leaf, file: Path, names: Container[str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether *dotted*, used at *node*, refers to one of *names*."""
        return self._resolver.qualify(dotted, file) in names or self._is_instance_member(
            dotted, node, file, names
        )

    def _references(self, node: BaseNode | Leaf) -> Iterable[str]:
        """Dotted names an annotation references: ``rpc.Dependency``, ``Service``, ..."""
        if isinstance(node, Name):
            yield node.value
            return
        if isinstance(node, Leaf):
            return
        children = node.children
        if node.type in {"atom_expr", "power"}:
            head = self._head(children)
            if head is not None:
                yield head[0]
                children = children[head[1] :]
        for child in children:
            yield from self._references(child)

    def _head(self, children: Sequence[BaseNode | Leaf]) -> tuple[str, int] | None:
        """The longest name chain at the head of an expression and its length in nodes.

        ``("rpc.Dependency", 2)`` for ``rpc.Dependency[...]``; None if it starts otherwise.
        """
        for end in range(len(children), 0, -1):
            dotted = self._scopes.dotted_name(children[:end])
            if dotted is not None:
                return dotted, end
        return None
