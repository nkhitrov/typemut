"""WidenType operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class WidenType(TypeMutationOperator):
    name = "WidenType"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_widenable_names(node, registry, mutations)
        return mutations


def _find_widenable_names(
    node: BaseNode | Leaf,
    registry: Registry,
    mutations: list[Mutation],
) -> None:
    """Recursively find Name nodes that can be widened to their base class."""
    if isinstance(node, Leaf) and node.type == "name":
        base = registry.get_base(node.value)
        if base is not None:
            mutations.append(
                Mutation(
                    file="",
                    operator="WidenType",
                    line=node.start_pos[0],
                    col=node.start_pos[1],
                    original=node.value,
                    mutated=base,
                    description=f"Widen {node.value} → {base}",
                )
            )
    elif isinstance(node, BaseNode):
        for child in node.children:
            _find_widenable_names(child, registry, mutations)
