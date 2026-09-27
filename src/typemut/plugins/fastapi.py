"""FastAPI plugin: do not mutate the signatures of endpoint functions.

FastAPI calls route handlers itself, via reflection; tests reach them over
HTTP. No Python code calls them, so the type checker has no caller to check a
mutated signature against: ``-> RedirectResponse`` mutated to
``-> RedirectResponse | None`` always survives. Such mutants are noise.

The plugin skips every parameter and return annotation of a function
decorated with a route method (``@app.get(...)``, ``@router.post(...)``, ...)
of an object that is provably a ``fastapi.FastAPI`` / ``fastapi.APIRouter``
instance, or an instance of a project class inheriting from them.
The receiver is resolved statically (see ``typemut.symbols``), never by its
variable name. Annotations inside the function body are mutated as usual.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry
from typemut.symbols import ScopeReader, SymbolResolver

# Classes whose instances register endpoints, under every name fastapi exports them.
APP_CLASSES = frozenset(
    (
        "fastapi.FastAPI",
        "fastapi.applications.FastAPI",
        "fastapi.APIRouter",
        "fastapi.routing.APIRouter",
    )
)

# Decorator methods of FastAPI / APIRouter that register a function FastAPI calls.
ROUTE_METHODS = frozenset(
    (
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
        "api_route",
        "websocket",
        "exception_handler",
        "middleware",
        "on_event",
    )
)

SIGNATURE = frozenset((AnnotationContext.PARAMETER, AnnotationContext.RETURN))


class FastAPIPlugin(Plugin):
    name = "fastapi"

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
        """No mutations for endpoint signatures; leave other annotations to the core."""
        if annotation.context not in SIGNATURE:
            return None
        decorators = self._decorators(annotation.node)
        if any(self._is_route(decorator, annotation.file) for decorator in decorators):
            return []
        return None

    def _is_route(self, decorator: BaseNode, file: Path) -> bool:
        """Whether a decorator is ``@<FastAPI or APIRouter instance>.<route method>(...)``."""
        expression = decorator.children[1]
        target = self._trailer_target(expression, "(")
        if target is None or target[0] not in ROUTE_METHODS:
            return False
        # Drop the `.method` and `(...)` trailers.
        receiver = self._scopes.dotted_name(expression.children[:-2])
        if receiver is None:
            return False
        class_name = self._resolver.instance_class(receiver, decorator, file)
        return class_name is not None and self._resolver.inherits_from(
            class_name, APP_CLASSES, file
        )

    def _decorators(self, annotation: BaseNode | Leaf) -> list[BaseNode]:
        """Decorators of the function whose signature holds the annotation."""
        # Parameter and return annotations only occur in function signatures.
        funcdef = annotation.search_ancestor("funcdef")
        assert funcdef is not None
        decorated = funcdef.parent
        if decorated is not None and decorated.type == "async_funcdef":
            decorated = decorated.parent
        if decorated is None or decorated.type != "decorated":
            return []
        decorators = decorated.children[0]
        if decorators.type == "decorator":
            return [decorators]
        return list(decorators.children)
