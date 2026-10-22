"""FastStream plugin: do not mutate the signatures of functions FastStream calls.

FastStream calls message handlers itself: it decodes the message body into the
handler's parameters (their annotations drive decoding: ``msg: User``
validates the body into ``User``, ``logger: Logger`` injects an object instead)
and publishes the handler's return value. Tests reach handlers by publishing
messages. No Python code calls them, so the type checker has no caller to check
a mutated signature against: ``-> str`` mutated to ``-> str | None`` always
survives, and ``msg: User`` widened to ``msg: BaseModel`` passes the checker but
breaks decoding at runtime. Such mutants are noise.

The plugin skips every parameter and return annotation of:

- handlers: functions decorated with ``@<receiver>.subscriber(...)`` or
  ``@<receiver>.publisher(...)``, registered with
  ``<receiver>.subscriber(...)(handler)``, or passed to a route
  (``KafkaRoute(handler, "topic")``);
- lifespan hooks: ``@app.on_startup`` / ``after_startup`` / ``on_shutdown`` /
  ``after_shutdown`` of a ``FastStream`` / ``AsgiFastStream`` instance, and
  ``@router.after_startup`` / ``on_broker_shutdown`` of a FastAPI integration
  router;
- functions passed by name as ``parser=``, ``decoder=``, ``middlewares=``,
  ``lifespan=`` or ``on_startup=``-style hooks to a broker, router, route,
  application, subscriber or publisher in the same module;
- dependency providers: ``Depends(provider)`` in the same module. The type
  checker does not relate ``Annotated[User, Depends(get_user)]`` to the
  return type of ``get_user``, so its signature has no checked caller either.

The receiver must provably be an instance of a FastStream broker / router /
application class (``faststream.kafka.KafkaBroker``,
``faststream.rabbit.RabbitRouter``, ``faststream.kafka.fastapi.KafkaRouter``,
``faststream.FastStream``, ...) or of a project class inheriting from one.
It is resolved statically (see ``typemut.symbols``), never by its variable
name. Annotations inside the function body are mutated as usual.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from parso.python.tree import BaseNode, Function, Leaf, Module, Name

from typemut.plugins.base import HandlerPlugin
from typemut.symbols import NamePatterns, ScopeReader, SymbolResolver

# Brokers and routers, under every name faststream exports them: ``faststream.kafka.KafkaBroker``,
# ``faststream.redis.broker.broker.RedisBroker``, ``faststream.nats.NatsRouter``,
# ``faststream.kafka.fastapi.KafkaRouter``, ``faststream_fastapi.KafkaRouter``, ...
BROKERS = ("faststream.*Broker", "faststream.*Router", "faststream_fastapi.*Router")

# Applications: ``faststream.FastStream``, ``faststream.asgi.AsgiFastStream``, ...
APPLICATIONS = ("faststream.*FastStream",)

# Routes (``KafkaRoute(handler, ...)``) and route publishers (``KafkaPublisher(...)``).
ROUTES = ("faststream.*Route",)
ROUTE_PUBLISHERS = ("faststream.*Publisher",)

# Broker / router methods that register a handler.
HANDLER_METHODS = ("subscriber", "publisher")

# Lifespan hook decorators: of applications, and of FastAPI integration routers.
APPLICATION_HOOKS = ("on_startup", "after_startup", "on_shutdown", "after_shutdown")
ROUTER_HOOKS = ("after_startup", "on_broker_shutdown")

# Decorators whose function FastStream calls: ``faststream.*Broker.subscriber``, ...
DECORATORS = NamePatterns(
    [f"{receiver}.{method}" for receiver in BROKERS for method in HANDLER_METHODS]
    + [f"{app}.{hook}" for app in APPLICATIONS for hook in APPLICATION_HOOKS]
    + [f"{router}.{hook}" for router in BROKERS for hook in ROUTER_HOOKS]
)

# Methods whose call result registers the function it is called with.
REGISTRARS = NamePatterns(
    f"{receiver}.{method}" for receiver in BROKERS for method in HANDLER_METHODS
)

# Classes whose constructors take framework-called functions as keyword arguments.
CONSTRUCTORS = NamePatterns(BROKERS + APPLICATIONS + ROUTES + ROUTE_PUBLISHERS)

# Dependency markers: ``Annotated[User, Depends(get_user)]`` (``faststream.Depends`` is
# ``fast_depends.Depends``).
DEPENDS = ("faststream.Depends", "faststream.params.Depends", "fast_depends.Depends")

# Callables whose first positional argument is a function FastStream calls.
FIRST_ARGUMENT_TAKERS = NamePatterns(ROUTES + DEPENDS)

# Keyword arguments that take a function (or a sequence of functions) FastStream calls.
CALLBACK_KEYWORDS = frozenset(
    ("call", "parser", "decoder", "middlewares", "lifespan", *APPLICATION_HOOKS)
)


class FastStreamPlugin(HandlerPlugin):
    name = "faststream"

    def __init__(
        self, resolver: SymbolResolver | None = None, scopes: ScopeReader | None = None
    ) -> None:
        super().__init__(resolver, scopes)
        # Per file: the tree last read and the names of the functions passed to FastStream in it.
        self._trees: dict[Path, Module] = {}
        self._registered: dict[Path, frozenset[str]] = {}

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        return any(
            self._is_registering(decorator, file) for decorator in self._decorators(funcdef)
        ) or funcdef.name.value in self._registered_names(funcdef, file)

    def _is_registering(
        self, decorator: BaseNode, file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether a decorator is ``@<broker>.subscriber(...)``, ``@<app>.on_startup``, ..."""
        reference = self._decorator_reference(decorator)
        return reference is not None and self._is_instance_member(
            reference.name, decorator, file, DECORATORS
        )

    def _registered_names(self, node: BaseNode, file: Path) -> frozenset[str]:
        """Names of the functions passed to FastStream calls in *file*, cached per tree."""
        tree = self._scopes.root(node)
        if self._trees.get(file) is not tree:
            self._trees[file] = tree
            self._registered[file] = frozenset(
                name.value
                for expression in self._expressions(tree)
                for name in self._callbacks(expression, file)
            )
        return self._registered[file]

    def _expressions(self, node: BaseNode) -> Iterable[BaseNode]:
        """Every ``a.b(...)``-style expression (``atom_expr``) under *node*."""
        for child in node.children:
            if isinstance(child, BaseNode):
                if child.type in {"atom_expr", "power"}:
                    yield child
                yield from self._expressions(child)

    def _callbacks(self, expression: BaseNode, file: Path) -> Iterable[Name]:
        """Names a FastStream call in *expression* receives as framework-called functions.

        ``KafkaBroker(parser=p)`` -> ``p``; ``KafkaRoute(handle, "t")`` -> ``handle``;
        ``broker.subscriber("t", decoder=d)(handle)`` -> ``d``, ``handle``.
        """
        children = expression.children
        for index, trailer in enumerate(children[1:], start=1):
            callee = self._scopes.dotted_name(children[:index])
            arguments = self._call_arguments(trailer)
            if callee is not None and arguments is not None:
                following = children[index + 1 : index + 2]
                yield from self._call_callbacks(callee, arguments, following, expression, file)

    def _call_callbacks(
        self,
        callee: str,
        arguments: Sequence[BaseNode | Leaf],
        following: Iterable[BaseNode | Leaf],
        node: BaseNode,
        file: Path,
    ) -> Iterable[Name]:
        """Callbacks of one call ``callee(*arguments)``, followed by the *following* trailer.

        ``callee`` is a class or function (``KafkaBroker``, ``Depends``), or a
        method of an instance (``broker.subscriber``).
        """
        registrar = self._is_instance_member(callee, node, file, REGISTRARS)
        if registrar or self._is_class(callee, file, CONSTRUCTORS):
            yield from self._keyword_callbacks(arguments)
        if self._is_class(callee, file, FIRST_ARGUMENT_TAKERS):
            yield from self._names(arguments[:1])
        if registrar:
            # `broker.subscriber(...)(handler)`
            for trailer in following:
                yield from self._names(self._call_arguments(trailer) or [])

    def _is_class(
        self, callee: str, file: Path, classes: NamePatterns
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether *callee* is one of *classes* or a project class inheriting from one."""
        qualified = self._resolver.qualify(callee, file)
        return qualified is not None and self._resolver.inherits_from(qualified, classes, file)

    def _call_arguments(self, trailer: BaseNode | Leaf) -> Sequence[BaseNode | Leaf] | None:
        """Arguments of a ``(...)`` trailer, None for other trailers."""
        if not isinstance(trailer, BaseNode) or trailer.type != "trailer":
            return None
        opening, inner = trailer.children[:2]
        if not isinstance(opening, Leaf) or opening.value != "(":
            return None
        if inner.type == "operator":
            # `()`: no arguments
            return []
        if inner.type == "arglist":
            return [argument for argument in inner.children if argument.type != "operator"]
        return [inner]

    def _keyword_callbacks(self, arguments: Iterable[BaseNode | Leaf]) -> Iterable[Name]:
        """Names passed as ``parser=``, ``middlewares=(...)``, ... among *arguments*."""
        for argument in arguments:
            if not isinstance(argument, BaseNode) or argument.type != "argument":
                continue
            keyword, operator, *value = argument.children
            if (
                isinstance(keyword, Name)
                and keyword.value in CALLBACK_KEYWORDS
                and isinstance(operator, Leaf)
                and operator.value == "="
            ):
                yield from self._names(value)

    def _names(self, values: Iterable[BaseNode | Leaf]) -> Iterable[Name]:
        """Plain names among *values*, also inside ``(a, b)`` / ``[a, b]`` literals."""
        for value in values:
            if isinstance(value, Name):
                yield value
            elif isinstance(value, BaseNode) and value.type in {"atom", "testlist_comp"}:
                yield from self._names(
                    [child for child in value.children if child.type != "operator"]
                )
