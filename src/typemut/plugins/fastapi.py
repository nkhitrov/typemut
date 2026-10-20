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

from pathlib import Path

from parso.python.tree import BaseNode, Function

from typemut.plugins.base import HandlerPlugin

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

# Qualified names of the route methods: ``fastapi.FastAPI.get``, ...
ROUTES = frozenset(f"{app}.{method}" for app in APP_CLASSES for method in ROUTE_METHODS)


class FastAPIPlugin(HandlerPlugin):
    name = "fastapi"

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        return any(self._is_route(decorator, file) for decorator in self._decorators(funcdef))

    def _is_route(self, decorator: BaseNode, file: Path) -> bool:
        """Whether a decorator is ``@<FastAPI or APIRouter instance>.<route method>(...)``."""
        reference = self._decorator_reference(decorator)
        return (
            reference is not None
            and reference.called
            and self._is_instance_member(reference.name, decorator, file, ROUTES)
        )
