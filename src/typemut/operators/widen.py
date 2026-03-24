"""WidenContainerType operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry

# Widening map: one step up the MRO toward more abstract types.
#
# Keys:   builtins (list, tuple, set, frozenset, dict) or legacy typing
#         generics (List, Tuple, Set, FrozenSet, Dict).
# Values: abstract types from collections.abc / typing (Sequence, AbstractSet,
#         Mapping, Collection, Iterable). These may NOT be imported in the
#         target file — import injection is handled by imports.py at mutation
#         application time.
WIDEN_MAP: dict[str, str] = {
    "list": "Sequence",
    "List": "Sequence",
    "tuple": "Sequence",
    "Tuple": "Sequence",
    "set": "AbstractSet",
    "Set": "AbstractSet",
    "frozenset": "AbstractSet",
    "FrozenSet": "AbstractSet",
    "dict": "Mapping",
    "Dict": "Mapping",
    "Sequence": "Collection",
    "AbstractSet": "Collection",
    "Mapping": "Collection",
    "Collection": "Iterable",
}


class WidenContainerType(TypeMutationOperator):
    name = "WidenContainerType"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_widenings(node, mutations)
        return mutations


def _find_widenings(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find container type names and generate widening mutations."""
    if isinstance(node, Leaf):
        if node.value in WIDEN_MAP and node.type == "name":
            widen_to = WIDEN_MAP[node.value]
            parent = node.parent
            if parent is not None and isinstance(parent, BaseNode):
                idx = parent.children.index(node)
                if idx + 1 < len(parent.children):
                    next_child = parent.children[idx + 1]
                    if (
                        isinstance(next_child, BaseNode)
                        and next_child.type == "trailer"
                    ):
                        # This is container[...] — widen the name, keep subscript
                        original_full = _node_code(node) + _node_code(next_child)
                        mutated = widen_to + _node_code(next_child)
                        mutations.append(
                            Mutation(
                                file="",
                                operator="WidenContainerType",
                                line=node.start_pos[0],
                                col=node.start_pos[1],
                                original=original_full,
                                mutated=mutated,
                                description=f"Widen {node.value} → {widen_to}",
                            )
                        )
                        return
            # Bare name (no subscript) — still widen
            mutations.append(
                Mutation(
                    file="",
                    operator="WidenContainerType",
                    line=node.start_pos[0],
                    col=node.start_pos[1],
                    original=node.value,
                    mutated=widen_to,
                    description=f"Widen {node.value} → {widen_to}",
                )
            )
            return

    if isinstance(node, BaseNode):
        for child in node.children:
            _find_widenings(child, mutations)
