"""SwapIteratorGenerator operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
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
WIDEN_TO: dict[str, str] = {
    "Iterator": "Iterable",
    "Generator": "Iterator",
    "AsyncIterator": "AsyncIterable",
    "AsyncGenerator": "AsyncIterator",
}


class SwapIteratorGenerator(TypeMutationOperator):
    name = "SwapIteratorGenerator"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_iterator_generator(node, mutations)
        return mutations


def _find_iterator_generator(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find iterator/generator type names and generate widening mutations."""
    if isinstance(node, Leaf) and node.type == "name" and node.value in WIDEN_TO:
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
                    params = _extract_params(next_child)
                    original = node.value + _node_code(next_child)
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
            _find_iterator_generator(child, mutations)


def _extract_params(trailer: BaseNode) -> list[str]:
    """Extract comma-separated type parameters from a trailer node like [X, Y, Z].

    The trailer structure is: '[' subscriptlist ']' (for multiple params)
    or: '[' single_expr ']' (for a single param).
    The subscriptlist contains children separated by ',' operators.
    """
    # Find the content between [ and ]
    inner_children = trailer.children[1:-1]  # skip '[' and ']'

    if not inner_children:
        return []

    # If there's a subscriptlist, split by comma operators
    content = inner_children[0]
    if isinstance(content, BaseNode) and content.type == "subscriptlist":
        params: list[str] = []
        current_parts: list[str] = []
        for child in content.children:
            code = _node_code(child)
            if child.type == "operator" and code.strip() == ",":
                params.append("".join(current_parts).strip())
                current_parts = []
            else:
                current_parts.append(code)
        if current_parts:
            params.append("".join(current_parts).strip())
        return params

    # Single parameter
    return [_node_code(content).strip()]
