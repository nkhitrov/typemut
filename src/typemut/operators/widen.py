"""WidenContainerType operator."""

from __future__ import annotations

from collections.abc import Mapping

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry

# Widening map: one step up the MRO toward more abstract types.
#
# Keys:   builtins (list, tuple, set, frozenset, dict) or legacy typing
#         generics (List, Tuple, Set, FrozenSet, Dict).
# Values: abstract types from collections.abc / typing (Sequence, AbstractSet,
#         Mapping, Collection, Iterable). These may NOT be imported in the
#         target file — import injection is handled by imports.py at mutation
#         application time.
WIDEN_MAP: Mapping[str, str] = {
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

TUPLE_NAMES = frozenset(("tuple", "Tuple"))
MAPPING_NAMES = frozenset(("Mapping",))


class WidenContainerType(TypeMutationOperator):
    name = "WidenContainerType"
    config_key = "widen-container-type"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        self._find_widenings(node, mutations)
        return mutations

    def _find_widenings(
        self,
        node: BaseNode | Leaf,
        mutations: list[Mutation],
    ) -> None:
        """Find container type names and generate widening mutations."""
        if (
            isinstance(node, Leaf)
            and node.value in WIDEN_MAP
            and node.type == "name"
            and not self._is_qualified_name(node)
        ):
            widen_to = WIDEN_MAP[node.value]
            parent = node.parent
            if parent is not None and isinstance(parent, BaseNode):
                idx = parent.children.index(node)
                if idx + 1 < len(parent.children):
                    next_child = parent.children[idx + 1]
                    if isinstance(next_child, BaseNode) and next_child.type == "trailer":
                        # This is container[...] — widen the name, adapt the subscript
                        subscript = self._widened_subscript(node.value, next_child)
                        if subscript is None:
                            return
                        original_full = self._node_code(node) + self._node_code(next_child)
                        mutated = widen_to + subscript
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
                self._find_widenings(child, mutations)

    def _widened_subscript(self, name: str, trailer: BaseNode) -> str | None:
        """Return the subscript for the widened type, or None if it can't be expressed.

        Most containers keep their subscript as is (list[X] -> Sequence[X]).
        Special cases, where a verbatim copy would produce an invalid type:
          tuple[X, ...] -> Sequence[X]
          tuple[X]      -> Sequence[X]
          tuple[A, B]   -> skipped (heterogeneous; no single-parameter equivalent)
          Mapping[K, V] -> Collection[K]
        """
        params = self._type_params(trailer)
        if name in TUPLE_NAMES:
            if len(params) == 2 and params[1] == "...":
                return f"[{params[0]}]"
            if len(params) == 1 and params[0] != "()":
                return f"[{params[0]}]"
            return None
        if name in MAPPING_NAMES and params:
            return f"[{params[0]}]"
        return self._node_code(trailer)
