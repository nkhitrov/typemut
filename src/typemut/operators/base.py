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


def is_qualified_name(leaf: Leaf) -> bool:
    """Check whether *leaf* is the attribute part of a dotted name (``module.name``)."""
    parent = leaf.parent
    return (
        parent is not None
        and parent.type == "trailer"
        and parent.children[0].type == "operator"
        and parent.children[0].get_code(include_prefix=False) == "."
    )


class TypeMutationOperator(ABC):
    name: str = ""
    # Key in [typemut.operators] / [typemut.ignore-types], e.g. "add-optional".
    config_key: str = ""

    @abstractmethod
    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Return all possible mutations for this annotation node."""
        ...
