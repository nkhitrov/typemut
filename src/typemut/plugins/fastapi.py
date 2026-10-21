"""FastAPI plugin: do not mutate the signatures of functions only FastAPI calls.

FastAPI calls route handlers itself, via reflection; tests reach them over
HTTP. No Python code calls them, so the type checker has no caller to check a
mutated signature against: ``-> RedirectResponse`` mutated to
``-> RedirectResponse | None`` always survives. Such mutants are noise, and
some are invalid at import: FastAPI rejects ``-> HTMLResponse | None`` on an
endpoint as a response model.

The plugin skips every parameter and return annotation of endpoints:
functions decorated with a route method (``@app.get(...)``,
``@router.post(...)``, ...) of an object that is provably an instance of
``fastapi.FastAPI`` / ``fastapi.APIRouter``, of a known third-party subclass
(FastStream's ``KafkaRouter``, ...), or of a project class inheriting from
them. The receiver is resolved statically (see ``typemut.symbols``), never
by its variable name.

It also skips the return annotation of dependency providers used only through
``Depends(...)`` / ``Security(...)`` and ``app.dependency_overrides`` (see
``typemut.plugins.dependencies``): ``Annotated[User, Depends(get_user)]`` does
not relate ``User`` to the return type of ``get_user``. Their parameters are
mutated: the provider's body and defaults check them like in any function.

Annotations inside function bodies are mutated as usual.
"""

from __future__ import annotations

from collections.abc import Container, Iterable
from pathlib import Path

from parso.python.tree import BaseNode, Function

from typemut.model import AnnotationContext
from typemut.plugins.base import SIGNATURE, HandlerPlugin
from typemut.plugins.dependencies import DependencyProviders
from typemut.symbols import NamePatterns, ScopeReader, SymbolResolver

# Classes whose instances register endpoints, under every name they are exported
# (``fnmatch`` patterns). Library classes are not parsed, so third-party
# subclasses of ``APIRouter`` are listed here.
APP_CLASSES = (
    "fastapi.FastAPI",
    "fastapi.applications.FastAPI",
    "fastapi.APIRouter",
    "fastapi.routing.APIRouter",
    # FastStream: faststream.kafka.fastapi.KafkaRouter, ..._internal.fastapi.router.StreamRouter
    "faststream.*.fastapi.*Router",
    "faststream_fastapi.*Router",
)

# What a dependency provider gets no mutations for.
PROVIDER = frozenset((AnnotationContext.RETURN,))

# Markers whose argument FastAPI calls as a dependency, under every name fastapi exports them.
DEPENDENCY_MARKERS = frozenset(
    f"fastapi.{module}{marker}"
    for module in ("", "params.", "param_functions.")
    for marker in ("Depends", "Security")
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


class FastAPIPlugin(HandlerPlugin):
    name = "fastapi"

    def __init__(
        self,
        resolver: SymbolResolver | None = None,
        scopes: ScopeReader | None = None,
        app_classes: Iterable[str] = APP_CLASSES,
        providers: DependencyProviders | None = None,
    ) -> None:
        super().__init__(resolver, scopes)
        app_classes = tuple(app_classes)
        # ``fastapi.FastAPI.get``, ...
        self._routes = NamePatterns(
            f"{app}.{method}" for app in app_classes for method in ROUTE_METHODS
        )
        self._providers = providers or DependencyProviders(
            DEPENDENCY_MARKERS,
            NamePatterns(f"{app}.dependency_overrides" for app in app_classes),
            self._resolver,
            self._scopes,
        )

    def scan(self, files: Iterable[Path]) -> None:
        """Find the dependency providers of the project."""
        self._providers.scan(files)

    def _skipped(
        self, funcdef: Function, file: Path
    ) -> Container[AnnotationContext]:  # pragma: no mutate (membership-tested)
        """All of an endpoint's signature, the return annotation of a dependency provider."""
        if self._is_handler(funcdef, file):
            return SIGNATURE
        if self._providers.is_provider(funcdef, file):
            return PROVIDER
        return frozenset()

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        """Whether *funcdef* is an endpoint."""
        return any(self._is_route(decorator, file) for decorator in self._decorators(funcdef))

    def _is_route(self, decorator: BaseNode, file: Path) -> bool:
        """Whether a decorator is ``@<FastAPI or APIRouter instance>.<route method>(...)``."""
        reference = self._decorator_reference(decorator)
        return (
            reference is not None
            and reference.called
            and self._is_instance_member(reference.name, decorator, file, self._routes)
        )
