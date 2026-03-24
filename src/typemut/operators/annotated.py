"""StripAnnotated operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class StripAnnotated(TypeMutationOperator):
    name = "StripAnnotated"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_annotated(node, mutations)
        return mutations


def _find_annotated(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find Annotated[X, ...] patterns and generate strip mutations."""
    if isinstance(node, Leaf):
        return

    children = node.children
    for i, child in enumerate(children):
        if isinstance(child, Leaf) and child.value == "Annotated" and i + 1 < len(children):
            trailer = children[i + 1]
            if isinstance(trailer, BaseNode) and trailer.type == "trailer":
                first_arg = _get_first_subscript_arg(trailer)
                if first_arg is not None:
                    # Build the full Annotated[...] code
                    original = _node_code(child) + _node_code(trailer)
                    mutated = _node_code(first_arg).strip()
                    mutations.append(
                        Mutation(
                            file="",
                            operator="StripAnnotated",
                            line=child.start_pos[0],
                            col=child.start_pos[1],
                            original=original,
                            mutated=mutated,
                            description=f"Strip Annotated → {mutated}",
                        )
                    )
                return  # Don't recurse into the Annotated itself

    for child in children:
        _find_annotated(child, mutations)


def _get_first_subscript_arg(trailer: BaseNode) -> BaseNode | Leaf | None:
    """Get the first argument from a trailer like [X, metadata, ...]."""
    for child in trailer.children:
        if isinstance(child, Leaf) and child.value in ("[]", "["):
            continue
        if isinstance(child, BaseNode) and child.type == "subscriptlist":
            # subscriptlist: X, metadata1, metadata2
            for sub in child.children:
                if isinstance(sub, Leaf) and sub.value == ",":
                    continue
                return sub  # First non-comma child is the type
        # Single subscript (no comma) — means Annotated[X] with no metadata
        if isinstance(child, Leaf) and child.type == "name":
            return child
        if isinstance(child, BaseNode):
            return child
    return None
