"""RemoveUnionMember operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class RemoveUnionMember(TypeMutationOperator):
    name = "RemoveUnionMember"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        members = _extract_union_members(node)
        if len(members) < 2:
            return []

        mutations: list[Mutation] = []
        original = _node_code(node)

        for i, member in enumerate(members):
            member_code = _node_code(member).strip()

            # Skip None removal — handled by RemoveOptional
            if member_code == "None":
                continue

            remaining = [m for j, m in enumerate(members) if j != i]
            remaining_codes = [_node_code(m).strip() for m in remaining]
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


def _extract_union_members(node: BaseNode | Leaf) -> list[BaseNode | Leaf]:
    """Extract members from a PEP 604 union (A | B | C).

    In parso, `A | B | C` is parsed as an `expr` node with children:
    [Name('A'), Operator('|'), Name('B'), Operator('|'), Name('C')]
    """
    if isinstance(node, Leaf):
        return []

    if node.type not in ("expr", "arith_expr"):
        return []

    has_pipe = any(isinstance(c, Leaf) and c.value == "|" for c in node.children)
    if not has_pipe:
        return []

    members: list[BaseNode | Leaf] = []
    for child in node.children:
        if isinstance(child, Leaf) and child.value == "|":
            continue
        members.append(child)

    return members
