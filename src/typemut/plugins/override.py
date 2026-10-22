"""Override: skip the signatures of methods decorated with ``@override``.

An ``@override`` method implements its parent's interface. Narrowing its
return (``-> X | None`` -> ``-> X``) or widening a parameter is still a legal
override, so such mutants always survive, and the opposite ones only show
that the type checker checks overrides. The parent's own signature is mutated
as usual, which is the meaningful check. Annotations in the method's body are
mutated too.

Unlike configured plugins this one is always on: :class:`MutationFinder`
asks it before any other plugin.
"""

from __future__ import annotations

from collections.abc import Container
from pathlib import Path
from typing import Final

from parso.python.tree import Function

from typemut.plugins.base import HandlerPlugin

OVERRIDE_DECORATORS: Final = frozenset(("typing.override", "typing_extensions.override"))


class OverridePlugin(HandlerPlugin):
    """Claims the parameter and return annotations of ``@override`` methods, with no mutations.

    The decorator is resolved through the file's imports: ``@override``,
    ``@typing.override``, ``@te.override`` (``import typing_extensions as te``)
    and aliases (``from typing import override as ov``) all match *names*.
    """

    name = "override"

    def __init__(self, names: Container[str] = OVERRIDE_DECORATORS) -> None:
        super().__init__()
        self._names = names

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        return any(
            reference is not None
            and not reference.called
            and self._resolver.qualify(reference.name, file) in self._names
            for reference in map(self._decorator_reference, self._decorators(funcdef))
        )
