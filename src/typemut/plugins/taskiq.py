"""taskiq plugin: do not mutate what the type checker cannot relate in taskiq DI.

Task signatures (``@broker.task``) are left to the core operators: ``.kiq()``
is typed with the task's ``ParamSpec``, so the type checker checks every call.
Dependency injection (``TaskiqDepends``, from taskiq-dependencies) is not
checked that way:

- **Provider returns.** A function or callable instance passed as
  ``TaskiqDepends(f)`` in a parameter of any function (a task or another
  provider) is called by taskiq. Its return annotation is checked only when
  some parameter has the provider as its default (``x: int = TaskiqDepends(f)``:
  ``TaskiqDepends`` returns what ``f`` returns). In
  ``x: Annotated[int, TaskiqDepends(f)]`` nothing relates ``int`` to ``f``, so
  when every reference is ``Annotated``, ``-> int`` mutated to
  ``-> int | None`` always survives: such returns are skipped. The provider's
  parameters are still mutated: defaults and body use check them.
- **The annotation is the dependency.** ``TaskiqDepends()`` without a provider
  makes taskiq take the dependency from the parameter's type hint: it looks
  ``Context``/``TaskiqState`` up by that type or constructs the class (also
  generics: ``GenericDep[Dep]`` builds ``Dep`` for ``T``). Any mutation of such
  an annotation (``Context | None``, a base class, another generic argument)
  changes what taskiq injects, usually crashing the worker, so the parameter
  gets no mutations.

Event handlers (``@broker.on_event``) and ``TaskiqMiddleware`` hooks need no
rules: ``on_event`` takes a typed ``Callable[[TaskiqState], ...]`` and hooks
override typed base methods, so the type checker checks both.

Names are resolved statically (see ``typemut.symbols``): ``TaskiqDepends`` by
its import, providers by their qualified name across the project files passed
to :meth:`TaskiqPlugin.scan`. Providers defined inside functions or nested
classes, built by a call (``TaskiqDepends(make())``) or reached through a
re-export are not recognized.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Function, Leaf, Name, Param

from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry
from typemut.symbols import ScopeReader, SymbolResolver

# ``TaskiqDepends`` under every name taskiq and taskiq-dependencies export it.
DEPENDS = frozenset(
    (
        "taskiq.TaskiqDepends",
        "taskiq_dependencies.Depends",
        "taskiq_dependencies.dependency.Depends",
    )
)


class TaskiqPlugin(Plugin):
    name = "taskiq"

    def __init__(
        self, resolver: SymbolResolver | None = None, scopes: ScopeReader | None = None
    ) -> None:
        self._scopes = scopes or ScopeReader()
        self._resolver = resolver or SymbolResolver(scopes=self._scopes)
        # What taskiq calls, by qualified name: ``mod.f``, ``mod.Class.__call__``.
        self._providers: set[str] = set()
        # Providers some parameter has as its default: their return is type-checked.
        self._checked: set[str] = set()

    def scan(self, files: Iterable[Path]) -> None:
        """Collect the providers that the parameters in *files* reference."""
        for file in files:
            tree = parso.parse(file.read_text())
            for funcdef in self._functions(tree):
                for param in funcdef.get_params():
                    self._collect(param, file)

    def find_mutations(
        self,
        annotation: AnnotationNode,
        # Unused: the signature mirrors Plugin.find_mutations.
        operators: Collection[TypeMutationOperator],  # pragma: no mutate
        registry: Registry,
    ) -> list[Mutation] | None:
        """No mutations for unchecked provider returns and type-hint dependencies."""
        if annotation.context is AnnotationContext.RETURN:
            # Return annotations only occur in function signatures.
            funcdef = annotation.node.search_ancestor("funcdef")
            assert isinstance(funcdef, Function)
            provider = self._qualified(funcdef, annotation.file)
            if provider in self._providers and provider not in self._checked:
                return []
        if annotation.context is AnnotationContext.PARAMETER:
            param = annotation.node.search_ancestor("param")
            assert isinstance(param, Param)
            if self._is_hint_dependency(param, annotation):
                return []
        return None

    def _collect(self, param: Param, file: Path) -> None:
        """Record the providers of a parameter's ``TaskiqDepends`` calls."""
        default = param.default
        arguments = None if default is None else self._depends_arguments(default, file)
        if arguments is not None:
            checked = self._called(arguments, file)
            self._providers.update(checked)
            self._checked.update(checked)
        if param.annotation is not None:
            for found in self._depends_calls(param.annotation, file):
                self._providers.update(self._called(found, file))

    def _called(self, arguments: BaseNode, file: Path) -> set[str]:
        """Qualified names of the provider of ``TaskiqDepends(<arguments>)``, if it has one."""
        provider = self._provider(arguments)
        dotted = None if provider is None else self._dotted(provider)
        if provider is None or dotted is None:
            return set()
        instance = self._resolver.instance_class(dotted, provider, file)
        names = {self._resolver.qualify(dotted, file)}
        names.add(None if instance is None else f"{instance}.__call__")
        return {name for name in names if name is not None}

    def _is_hint_dependency(
        self, param: Param, annotation: AnnotationNode
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether taskiq takes the parameter's dependency from its annotation."""
        calls = list(self._depends_calls(annotation.node, annotation.file))
        default = param.default
        arguments = None if default is None else self._depends_arguments(default, annotation.file)
        if arguments is not None:
            calls.append(arguments)
        return any(self._provider(arguments) is None for arguments in calls)

    def _depends_calls(self, node: BaseNode | Leaf, file: Path) -> Iterable[BaseNode]:
        """Argument trailers of the ``TaskiqDepends(...)`` calls in an annotation."""
        arguments = self._depends_arguments(node, file)
        if arguments is not None:
            yield arguments
        if isinstance(node, BaseNode):
            for child in node.children:
                yield from self._depends_calls(child, file)

    def _depends_arguments(self, node: BaseNode | Leaf, file: Path) -> BaseNode | None:
        """The ``(...)`` trailer if *node* calls ``TaskiqDepends`` (resolved through imports)."""
        found = self._trailer_target(node, "(")
        if found is None:
            return None
        trailer = found[1]
        call = trailer.parent
        assert call is not None
        callee = self._scopes.dotted_name(call.children[:-1])
        if callee is None or self._resolver.qualify(callee, file) not in DEPENDS:
            return None
        return trailer

    def _provider(self, arguments: BaseNode) -> BaseNode | Leaf | None:
        """The provider passed to ``TaskiqDepends``: the first positional or ``dependency=``."""
        nodes = arguments.children[1:-1]
        if nodes and nodes[0].type == "arglist":
            nodes = nodes[0].children[::2]
        for node in nodes:
            if isinstance(node, Leaf):
                return node
            assert isinstance(node, BaseNode)
            if node.type != "argument":
                return node
            keyword = node.children[0]
            if isinstance(keyword, Name) and keyword.value == "dependency":
                return node.children[-1]
        return None

    def _dotted(self, node: BaseNode | Leaf) -> str | None:
        """Dotted name of ``name`` or ``mod.name``, else None."""
        if isinstance(node, Name):
            return node.value
        if not isinstance(node, BaseNode) or node.type not in {"atom_expr", "power"}:
            return None
        return self._scopes.dotted_name(node.children)

    def _qualified(self, funcdef: Function, file: Path) -> str | None:
        """``mod.f`` for a module-level function, ``mod.Class.f`` for a method.

        None for functions nested in functions or in nested classes.
        """
        name = funcdef.name.value
        scope = funcdef.search_ancestor("classdef", "funcdef")
        if scope is not None:
            if scope.type != "classdef" or scope.search_ancestor("classdef", "funcdef"):
                return None
            name = f"{scope.children[1].value}.{name}"
        return self._resolver.qualify(name, file)

    def _functions(self, node: BaseNode) -> Iterable[Function]:
        """Every function defined in *node*, nested ones included."""
        for child in node.children:
            if isinstance(child, Function):
                yield child
            if isinstance(child, BaseNode):
                yield from self._functions(child)
