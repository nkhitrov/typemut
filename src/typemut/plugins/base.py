"""Abstract base for library plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from typemut.discovery import AnnotationNode
from typemut.operators.base import Mutation, TypeMutationOperator

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typemut.registry import Registry


class Plugin(ABC):
    """Library-specific knowledge layered on top of the core operators.

    Core operators are library-agnostic. Libraries that wrap user types in
    their own generics (``Mapped[...]`` in SQLAlchemy, for example) give some
    of the core mutations a different meaning: a mutation can be invalid for
    the library at runtime, or have to be applied inside the wrapper.
    A plugin claims such annotations and decides which mutations they get.
    """

    name: str = ""

    def operators(self) -> list[TypeMutationOperator]:
        """Return extra, library-specific operators run on every annotation."""
        return []

    @abstractmethod
    def find_mutations(
        self,
        annotation: AnnotationNode,
        operators: Sequence[TypeMutationOperator],
        registry: Registry,
    ) -> list[Mutation] | None:
        """Return the mutations for an annotation this plugin owns.

        Return None to leave the annotation to the core operators.
        """
        ...
