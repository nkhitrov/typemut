"""SwapIteratorGenerator operator."""

from __future__ import annotations

from collections.abc import Mapping

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry

# Subscripted swap rules (widening only — each step drops a capability):
#   Iterator[Y] -> Iterable[Y]
#   Generator[Y, S, R] -> Iterator[Y]   (keep first param)
#   AsyncIterator[Y] -> AsyncIterable[Y]
#   AsyncGenerator[Y, S] -> AsyncIterator[Y]   (keep first param)
#
# Narrowing swaps (Iterator -> Generator, Iterable -> Iterator) are not
# generated: their outcome is predetermined. Iterator -> Generator is an
# equivalent mutant on generator functions, and Iterable -> Iterator is killed
# by any caller passing a list.

# All types in this operator are from collections.abc / typing.
# The source type is already imported in the target file, but the
# replacement type may not be — import injection is handled by
# imports.py at mutation application time.
WIDEN_TO: Mapping[str, str] = {
    "Iterator": "Iterable",
    "Generator": "Iterator",
    "AsyncIterator": "AsyncIterable",
    "AsyncGenerator": "AsyncIterator",
}


class SwapIteratorGenerator(TypeMutationOperator):
    name = "SwapIteratorGenerator"
    config_key = "swap-iterator-generator"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        self._find_iterator_generator(node, mutations)
        return mutations

    def _find_iterator_generator(
        self,
        node: BaseNode | Leaf,
        mutations: list[Mutation],
    ) -> None:
        """Find iterator/generator type names and generate widening mutations."""
        if (
            isinstance(node, Leaf)
            and node.type == "name"
            and node.value in WIDEN_TO
            and not self._is_qualified_name(node)
        ):
            target = WIDEN_TO[node.value]
            original = node.value
            mutated = target
            parent = node.parent
            if parent is not None:
                idx = parent.children.index(node)
                if idx + 1 < len(parent.children):
                    next_child = parent.children[idx + 1]
                    if isinstance(next_child, BaseNode) and next_child.type == "trailer":
                        # Keep only the yield type: Generator[Y, S, R] -> Iterator[Y]
                        params = self._type_params(next_child)
                        original = node.value + self._node_code(next_child)
                        mutated = f"{target}[{params[0] if params else ''}]"

            mutations.append(
                Mutation(
                    file="",
                    operator="SwapIteratorGenerator",
                    line=node.start_pos[0],
                    col=node.start_pos[1],
                    original=original,
                    mutated=mutated,
                    description=f"Swap {node.value} → {target}",
                )
            )
            return

        if isinstance(node, BaseNode):
            for child in node.children:
                self._find_iterator_generator(child, mutations)
