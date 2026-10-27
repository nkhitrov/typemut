"""django-modern-rest (dmr) plugin: do not mutate the return annotations of endpoints.

dmr calls controller endpoints itself and reads their return annotations
when the controller class is created, to build the response schema and
validation. No Python code calls an endpoint, so the type checker has no
caller to check a mutated return type against: ``-> UserModel`` mutated to
``-> UserModel | None`` always survives, and some such mutants even break
the controller at import time (``-> AsyncIterator[X] | None`` on a streaming
endpoint, any change next to explicit ``responses=``).

An endpoint is a method named after an HTTP method (``get``, ``post``, ...,
``meta`` for OPTIONS) of a class inheriting from ``dmr.Controller`` or a
dmr streaming controller, directly or through project classes, or any
function decorated with ``@modify`` (``dmr.modify``, ``dmr.streaming.modify``
or a ``ModifyEndpoint(...)`` instance). Its return annotation is skipped
unless it is decorated with ``@validate`` (in the same forms): ``validate`` binds the return
type to ``HttpResponse``, so the type checker does check it.

Everything else is mutated as usual:

- endpoint parameters (``parsed_body: Body[UserModel]``): the endpoint body
  uses them, so the type checker checks a mutated parameter there;
- other controller methods and attributes (``to_error``, ``handle_*_error``,
  ``request: AuthenticatedHttpRequest[User]``): they override ``Controller``
  API and are checked against it;
- methods of dmr's ready-made controllers (JWT, token, session views)
  overridden in a subclass: they are checked against the method they override.
"""

from __future__ import annotations

from collections.abc import Container
from http import HTTPMethod
from pathlib import Path

from parso.python.tree import Function

from typemut.model import AnnotationContext
from typemut.plugins.base import HandlerPlugin
from typemut.symbols import NamePatterns

# Controllers whose subclasses define endpoints, under every name dmr exports them.
CONTROLLER_CLASSES = NamePatterns(
    ("dmr.Controller", "dmr.controller.Controller", "dmr.streaming.*Controller")
)

# Endpoint method names: ``Controller.allowed_http_methods``, OPTIONS is served by ``meta``.
ENDPOINT_METHODS = frozenset(method.lower() for method in HTTPMethod) - {"options"} | {"meta"}

# Endpoint decorators: the default instances (``dmr.modify``, ``dmr.streaming.validate``, ...)
# and instances of their classes created by the project (``ValidateEndpoint(MyExtras)``).
MODIFY = NamePatterns(("dmr.modify", "dmr.*.modify"))
MODIFY_CLASSES = NamePatterns(("dmr.*ModifyEndpoint",))
VALIDATE = NamePatterns(("dmr.validate", "dmr.*.validate"))
VALIDATE_CLASSES = NamePatterns(("dmr.*ValidateEndpoint",))
RETURN = frozenset((AnnotationContext.RETURN,))


class DmrPlugin(HandlerPlugin):
    name = "dmr"

    def _skipped(self, funcdef: Function, file: Path) -> Container[AnnotationContext]:
        """The return annotation of an endpoint, unless ``@validate`` checks it."""
        if self._is_handler(funcdef, file) and not self._has_decorator(
            funcdef, file, VALIDATE, VALIDATE_CLASSES
        ):
            return RETURN
        return frozenset()

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        """Whether *funcdef* is an endpoint: an HTTP method of a controller or ``@modify``-ed."""
        if self._has_decorator(funcdef, file, MODIFY, MODIFY_CLASSES):
            return True
        return funcdef.name.value in ENDPOINT_METHODS and self._is_method_of(
            funcdef, file, CONTROLLER_CLASSES
        )

    def _has_decorator(
        self, funcdef: Function, file: Path, names: Container[str], classes: Container[str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether a decorator of *funcdef* is ``@<one of names>(...)`` or ``@<instance>(...)``.

        The instance has to be of one of *classes*; ``.lazy(...)`` counts too.
        """
        for decorator in self._decorators(funcdef):
            reference = self._decorator_reference(decorator)
            if reference is None:
                continue
            target = reference.name.removesuffix(".lazy")
            if self._resolver.qualify(target, file) in names:
                return True
            if self._resolver.instance_class(target, decorator, file) in classes:
                return True
        return False
