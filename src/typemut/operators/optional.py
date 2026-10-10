"""RemoveOptional and AddOptional operators."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry


class RemoveOptional(TypeMutationOperator):
    name = "RemoveOptional"
    config_key = "remove-optional"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Detect X | None and generate mutation removing None."""
        members = self._union_members(node)
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

        remaining_codes = [self._node_code(m).strip() for m in remaining]
        mutated = " | ".join(remaining_codes)
        original = self._node_code(node)

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
    config_key = "add-optional"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Add None to a type that doesn't already have it.

        Only applies to return types and class fields — adding None to
        parameters has low value since callers simply won't pass None.
        TypeVar declarations are skipped: ``TypeVar("T") | None`` is not a
        type annotation, and the checker error it causes is not a real kill.
        ``TypeAlias`` annotations are skipped for the same reason:
        ``TypeAlias | None`` is not a valid type.
        """
        if context in {AnnotationContext.PARAMETER, AnnotationContext.TYPEVAR}:
            return []

        code = self._node_code(node).strip()

        if code.rpartition(".")[2] == "TypeAlias":
            return []

        # Skip if already contains None
        if self._contains_none(node):
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

    def _contains_none(self, node: BaseNode | Leaf) -> bool:
        """Check if a node contains None anywhere."""
        if isinstance(node, Leaf):
            return node.value == "None"
        return any(self._contains_none(child) for child in node.children)
