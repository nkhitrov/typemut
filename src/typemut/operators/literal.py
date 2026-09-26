"""RemoveLiteralMember operator."""

from __future__ import annotations

from itertools import pairwise

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class RemoveLiteralMember(TypeMutationOperator):
    """Remove one value from a multi-value ``Literal[...]``.

    Survived = the removed value is never passed/returned/assigned in typed code.
    """

    name = "RemoveLiteralMember"
    config_key = "remove-literal-member"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        for subscripts in _find_literal_subscriptlists(node):
            members = [c for c in subscripts.children if not _is_comma(c)]
            for i, member in enumerate(members):
                remaining = [_node_code(m).strip() for j, m in enumerate(members) if j != i]
                member_code = _node_code(member).strip()
                mutations.append(
                    Mutation(
                        file="",
                        operator=self.name,
                        line=node.start_pos[0],
                        col=node.start_pos[1],
                        original=_node_code(node),
                        mutated=_render_replacing(node, subscripts, ", ".join(remaining)),
                        description=f"Remove {member_code} from Literal",
                    )
                )
        return mutations


def _find_literal_subscriptlists(node: BaseNode | Leaf) -> list[BaseNode]:
    """Find the subscriptlist of every ``Literal[a, b, ...]`` (2+ values) in *node*."""
    if isinstance(node, Leaf):
        return []

    results: list[BaseNode] = []
    children = node.children
    for prev, child in pairwise(children):
        if isinstance(child, BaseNode) and _is_subscript_trailer(child) and _is_literal_name(prev):
            content = child.children[1]
            if isinstance(content, BaseNode) and content.type == "subscriptlist":
                results.append(content)

    for child in children:
        results.extend(_find_literal_subscriptlists(child))
    return results


def _is_literal_name(node: BaseNode | Leaf) -> bool:
    """Match ``Literal`` or the ``.Literal`` trailer of ``typing.Literal``."""
    if isinstance(node, Leaf):
        return node.value == "Literal"
    return (
        node.type == "trailer"
        and len(node.children) == 2
        and isinstance(node.children[1], Leaf)
        and node.children[1].value == "Literal"
    )


def _is_subscript_trailer(node: BaseNode) -> bool:
    return (
        node.type == "trailer"
        and isinstance(node.children[0], Leaf)
        and node.children[0].value == "["
    )


def _is_comma(node: BaseNode | Leaf) -> bool:
    return isinstance(node, Leaf) and node.value == ","


def _render_replacing(root: BaseNode | Leaf, target: BaseNode, replacement: str) -> str:
    """Render *root* source with *target* subtree replaced by *replacement*."""

    def render(node: BaseNode | Leaf) -> str:
        if node is target:
            return target.get_first_leaf().prefix + replacement
        if isinstance(node, Leaf):
            return node.prefix + node.value
        return "".join(render(child) for child in node.children)

    return render(root)[len(root.get_first_leaf().prefix) :]
