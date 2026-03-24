"""RemoveOptional and AddOptional operators."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class RemoveOptional(TypeMutationOperator):
    name = "RemoveOptional"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Detect X | None and generate mutation removing None."""
        members = _extract_union_members(node)
        if len(members) < 2:
            return []

        none_indices = [
            i for i, m in enumerate(members) if isinstance(m, Leaf) and m.value == "None"
        ]
        if not none_indices:
            return []

        remaining = [m for i, m in enumerate(members) if i not in none_indices]
        if not remaining:
            return []

        remaining_codes = [_node_code(m).strip() for m in remaining]
        mutated = " | ".join(remaining_codes)
        original = _node_code(node)

        return [
            Mutation(
                file="",
                operator=self.name,
                line=node.start_pos[0],
                col=node.start_pos[1],
                original=original,
                mutated=mutated,
                description=f"Remove Optional (None) → {mutated}",
            )
        ]


class AddOptional(TypeMutationOperator):
    name = "AddOptional"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Add None to a type that doesn't already have it.

        Only applies to return types and class fields — adding None to
        parameters has low value since callers simply won't pass None.
        """
        if context == AnnotationContext.PARAMETER:
            return []

        # Skip self parameter
        if isinstance(node, Leaf) and node.value == "self":
            return []

        code = _node_code(node).strip()

        # Skip if already contains None
        if _contains_none(node):
            return []

        # Skip None itself
        if code == "None":
            return []

        mutated = f"{code} | None"
        return [
            Mutation(
                file="",
                operator=self.name,
                line=node.start_pos[0],
                col=node.start_pos[1],
                original=code,
                mutated=mutated,
                description=f"Add Optional: {code} → {mutated}",
            )
        ]


def _contains_none(node: BaseNode | Leaf) -> bool:
    """Check if a node contains None anywhere."""
    if isinstance(node, Leaf):
        return node.value == "None"
    return any(_contains_none(child) for child in node.children)


def _extract_union_members(node: BaseNode | Leaf) -> list[BaseNode | Leaf]:
    """Extract members from a PEP 604 union."""
    if isinstance(node, Leaf):
        return []
    if node.type not in ("expr", "arith_expr"):
        return []
    has_pipe = any(isinstance(c, Leaf) and c.value == "|" for c in node.children)
    if not has_pipe:
        return []
    return [c for c in node.children if not (isinstance(c, Leaf) and c.value == "|")]
