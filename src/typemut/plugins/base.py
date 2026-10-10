"""Abstract base for library plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationNode, Mutation
from typemut.nodes import NodeSource
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry


class Plugin(NodeSource, ABC):
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
        operators: Collection[TypeMutationOperator],
        registry: Registry,
    ) -> list[Mutation] | None:
        """Return the mutations for an annotation this plugin owns.

        Return None to leave the annotation to the core operators.
        """
        ...

    def _trailer_target(self, node: BaseNode | Leaf, bracket: str) -> tuple[str, BaseNode] | None:
        """For ``name[...]``/``a.name(...)`` return the name and the last trailer."""
        if not isinstance(node, BaseNode) or node.type not in {"atom_expr", "power"}:
            return None
        trailer = node.children[-1]
        if not isinstance(trailer, BaseNode) or trailer.type != "trailer":
            return None
        opening = trailer.children[0]
        if not isinstance(opening, Leaf) or opening.value != bracket:
            return None

        target = node.children[-2]
        if isinstance(target, BaseNode) and target.type == "trailer":
            # Attribute access: `.name`
            target = target.children[-1]
        if not isinstance(target, Leaf) or target.type != "name":
            return None
        return target.value, trailer
