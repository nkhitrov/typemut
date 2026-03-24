"""Abstract base for mutation operators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typemut.registry import Registry


@dataclass
class Mutation:
    file: str
    operator: str
    line: int
    col: int
    original: str
    mutated: str
    description: str
    # Full import line needed for the mutated type, e.g. "from abc import ABC".
    # None when no import is needed (builtins or already in scope).
    required_import: str | None = None


class TypeMutationOperator(ABC):
    name: str = ""

    @abstractmethod
    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Return all possible mutations for this annotation node."""
        ...
