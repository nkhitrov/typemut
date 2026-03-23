"""SwapLiteralValue operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class SwapLiteralValue(TypeMutationOperator):
    name = "SwapLiteralValue"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Find Literal[value] patterns and swap values from the pool."""
        literals = _find_literal_subscripts(node)
        if not literals:
            return []

        mutations: list[Mutation] = []
        original = _node_code(node)

        # Get the file path from the node's module
        file_path = _get_file_path(node)
        pool = registry.get_file_literals(file_path) if file_path else registry.literal_pool

        for lit_value, lit_node in literals:
            for other in pool:
                if other != lit_value:
                    mutated = original.replace(lit_value, other, 1)
                    mutations.append(
                        Mutation(
                            file="",
                            operator=self.name,
                            line=node.start_pos[0],
                            col=node.start_pos[1],
                            original=original,
                            mutated=mutated,
                            description=f"Swap Literal {lit_value} → {other}",
                        )
                    )

        return mutations


def _get_file_path(node: BaseNode | Leaf) -> str:
    """Walk up to the module root to find file path."""
    current = node
    while current.parent is not None:
        current = current.parent
    # parso Module nodes don't store file paths directly
    # We'll use the registry's global pool as fallback
    return ""


def _find_literal_subscripts(
    node: BaseNode | Leaf,
) -> list[tuple[str, BaseNode | Leaf]]:
    """Find Literal[X] patterns in the node and return (value, value_node) pairs."""
    results: list[tuple[str, BaseNode | Leaf]] = []

    if isinstance(node, Leaf):
        return results

    children = node.children
    for i, child in enumerate(children):
        if isinstance(child, Leaf) and child.value == "Literal":
            # Next sibling should be trailer: [subscript]
            if i + 1 < len(children):
                trailer = children[i + 1]
                if isinstance(trailer, BaseNode) and trailer.type == "trailer":
                    for tc in trailer.children:
                        if isinstance(tc, Leaf) and tc.type in ("string", "number"):
                            results.append((tc.value, tc))
                        elif isinstance(tc, BaseNode) and tc.type == "subscriptlist":
                            for sub in tc.children:
                                if isinstance(sub, Leaf) and sub.type in (
                                    "string",
                                    "number",
                                ):
                                    results.append((sub.value, sub))

    # Recurse into children
    for child in children:
        results.extend(_find_literal_subscripts(child))

    return results
