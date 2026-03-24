"""TupleEllipsis operator — mutates tuple[int] <-> tuple[int, ...]."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry

TUPLE_NAMES = {"tuple", "Tuple"}


class TupleEllipsis(TypeMutationOperator):
    name = "TupleEllipsis"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        _find_tuple_ellipsis(node, mutations)
        return mutations


def _find_tuple_ellipsis(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find tuple[X] or tuple[X, ...] and generate ellipsis mutations."""
    if isinstance(node, Leaf) and node.value in TUPLE_NAMES and node.type == "name":
        parent = node.parent
        if parent is not None and isinstance(parent, BaseNode):
            idx = parent.children.index(node)
            if idx + 1 < len(parent.children):
                trailer = parent.children[idx + 1]
                if isinstance(trailer, BaseNode) and trailer.type == "trailer":
                    _process_trailer(node, trailer, mutations)
                    return

    if isinstance(node, BaseNode):
        for child in node.children:
            _find_tuple_ellipsis(child, mutations)


def _process_trailer(
    name_node: Leaf,
    trailer: BaseNode,
    mutations: list[Mutation],
) -> None:
    """Analyze trailer contents and produce mutations."""
    # trailer.children: '[', content..., ']'
    # Get meaningful children (skip '[' and ']')
    inner = trailer.children[1:-1]
    if not inner:
        return

    # Collect meaningful (non-whitespace) elements from inner content
    # The inner content may be a single node or a subscriptlist
    meaningful: list[BaseNode | Leaf] = []
    commas: list[Leaf] = []

    # If there's a subscriptlist, expand its children; otherwise use inner directly
    content_nodes: list[BaseNode | Leaf] = []
    for n in inner:
        if isinstance(n, BaseNode) and n.type == "subscriptlist":
            content_nodes.extend(n.children)
        else:
            content_nodes.append(n)

    for child in content_nodes:
        if isinstance(child, Leaf) and child.value == ",":
            commas.append(child)
        elif isinstance(child, Leaf) and child.value.strip() == "":
            continue
        else:
            meaningful.append(child)

    if not meaningful:
        return

    # Skip empty tuple: tuple[()]
    if (
        len(meaningful) == 1
        and isinstance(meaningful[0], BaseNode)
        and _node_code(meaningful[0]).strip() == "()"
    ):
        return
    if (
        len(meaningful) == 1
        and isinstance(meaningful[0], Leaf)
        and meaningful[0].value.strip() == "()"
    ):
        return

    original_full = _node_code(name_node) + _node_code(trailer)
    last = meaningful[-1]
    last_is_ellipsis = isinstance(last, Leaf) and last.value == "..."

    if last_is_ellipsis and len(meaningful) >= 2:
        # tuple[int, ...] -> tuple[int]
        # Remove the ellipsis and preceding comma
        # Rebuild: name_node.value + '[' + all type args (without trailing , ...) + ']'
        type_args = meaningful[:-1]  # everything except ...
        type_text = ", ".join(_node_code(t).strip() for t in type_args)
        mutated = f"{name_node.value}[{type_text}]"
        mutations.append(
            Mutation(
                file="",
                operator="TupleEllipsis",
                line=name_node.start_pos[0],
                col=name_node.start_pos[1],
                original=original_full,
                mutated=mutated,
                description=f"Remove ellipsis from {original_full.strip()}",
            )
        )
    elif not last_is_ellipsis and len(meaningful) == 1 and len(commas) == 0:
        # tuple[int] -> tuple[int, ...]
        # Single type arg, no commas — add ellipsis
        type_text = _node_code(meaningful[0]).strip()
        mutated = f"{name_node.value}[{type_text}, ...]"
        mutations.append(
            Mutation(
                file="",
                operator="TupleEllipsis",
                line=name_node.start_pos[0],
                col=name_node.start_pos[1],
                original=original_full,
                mutated=mutated,
                description=f"Add ellipsis to {original_full.strip()}",
            )
        )
    # else: multi-element fixed tuple like tuple[int, str] — skip
