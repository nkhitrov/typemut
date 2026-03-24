"""SwapContainerType operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry

# Swap groups: each container swaps with compatible alternatives.
#
# All types here are either Python builtins (list, tuple, set, frozenset) or
# legacy typing generics (List, Tuple, Set, FrozenSet). Since both source and
# target types are in the same category, no additional imports are needed.
SWAP_MAP: dict[str, list[str]] = {
    "list": ["tuple"],
    "tuple": ["list"],
    "set": ["frozenset"],
    "frozenset": ["set"],
    "List": ["Tuple"],
    "Tuple": ["List"],
    "Set": ["FrozenSet"],
    "FrozenSet": ["Set"],
}


class SwapContainerType(TypeMutationOperator):
    name = "SwapContainerType"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_containers(node, mutations)
        return mutations


def _find_containers(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find container type names followed by [...] and generate swaps."""
    if isinstance(node, Leaf):
        if node.value in SWAP_MAP and node.type == "name":
            # Check if followed by a trailer (subscript)
            parent = node.parent
            if parent is not None and isinstance(parent, BaseNode):
                idx = parent.children.index(node)
                if idx + 1 < len(parent.children):
                    next_child = parent.children[idx + 1]
                    if (
                        isinstance(next_child, BaseNode)
                        and next_child.type == "trailer"
                    ):
                        # This is container[...] — generate swaps
                        original_full = _node_code(node) + _node_code(next_child)
                        for swap_to in SWAP_MAP[node.value]:
                            mutated = swap_to + _node_code(next_child)
                            mutations.append(
                                Mutation(
                                    file="",
                                    operator="SwapContainerType",
                                    line=node.start_pos[0],
                                    col=node.start_pos[1],
                                    original=original_full,
                                    mutated=mutated,
                                    description=f"Swap {node.value} → {swap_to}",
                                )
                            )
                        return

    if isinstance(node, BaseNode):
        for child in node.children:
            _find_containers(child, mutations)
