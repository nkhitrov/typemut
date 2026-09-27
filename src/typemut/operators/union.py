"""RemoveUnionMember operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class RemoveUnionMember(TypeMutationOperator):
    name = "RemoveUnionMember"
    config_key = "remove-union-member"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        members = self._union_members(node)
        if len(members) < 2:
            return []

        mutations: list[Mutation] = []
        original = self._node_code(node)

        for i, member in enumerate(members):
            member_code = self._node_code(member).strip()

            # Skip None removal — handled by RemoveOptional
            if member_code == "None":
                continue

            remaining = [m for j, m in enumerate(members) if j != i]
            remaining_codes = [self._node_code(m).strip() for m in remaining]

            # Skip X | None -> None: degenerate, and RemoveOptional covers X | None
            if remaining_codes == ["None"]:
                continue
            mutated = " | ".join(remaining_codes)

            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=node.start_pos[0],
                    col=node.start_pos[1],
                    original=original,
                    mutated=mutated,
                    description=f"Remove {member_code} from union",
                )
            )

        return mutations
