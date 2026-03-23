"""SwapSiblingType operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class SwapSiblingType(TypeMutationOperator):
    name = "SwapSiblingType"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_swappable_names(node, registry, mutations)
        return mutations


def _find_swappable_names(
    node: BaseNode | Leaf,
    registry: Registry,
    mutations: list[Mutation],
) -> None:
    """Recursively find Name nodes that have siblings in the hierarchy."""
    if isinstance(node, Leaf) and node.type == "name":
        siblings = registry.get_siblings(node.value)
        if siblings:
            original = node.value
            for sibling in siblings:
                mutations.append(
                    Mutation(
                        file="",
                        operator="SwapSiblingType",
                        line=node.start_pos[0],
                        col=node.start_pos[1],
                        original=original,
                        mutated=sibling,
                        description=f"Swap {original} → {sibling}",
                    )
                )
    elif isinstance(node, BaseNode):
        for child in node.children:
            _find_swappable_names(child, registry, mutations)
