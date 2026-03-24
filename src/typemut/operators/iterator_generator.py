"""SwapIteratorGenerator operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry

# Maps each type name to a list of (target_name, param_transform) tuples.
# param_transform is a callable: (list[str]) -> list[str] | None
# For bare forms, param_transform is ignored and only the name is swapped.

# Subscripted swap rules:
#   Iterator[Y] -> Generator[Y, None, None]
#   Iterator[Y] -> Iterable[Y]
#   Generator[Y, S, R] -> Iterator[Y]   (keep first param)
#   AsyncIterator[Y] -> AsyncGenerator[Y, None]
#   AsyncIterator[Y] -> AsyncIterable[Y]
#   AsyncGenerator[Y, S] -> AsyncIterator[Y]   (keep first param)
#   Iterable[Y] -> Iterator[Y]
#   AsyncIterable[Y] -> AsyncIterator[Y]

# All types in this operator are from collections.abc / typing.
# The source type is already imported in the target file, but the
# replacement type may not be — import injection is handled by
# imports.py at mutation application time.
TARGET_NAMES = {
    "Iterator",
    "Generator",
    "AsyncIterator",
    "AsyncGenerator",
    "Iterable",
    "AsyncIterable",
}

# Bare form swap rules (no subscript)
BARE_SWAPS: dict[str, list[str]] = {
    "Iterator": ["Generator", "Iterable"],
    "Generator": ["Iterator"],
    "AsyncIterator": ["AsyncGenerator", "AsyncIterable"],
    "AsyncGenerator": ["AsyncIterator"],
    "Iterable": ["Iterator"],
    "AsyncIterable": ["AsyncIterator"],
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


def _find_iterator_generator(
    node: BaseNode | Leaf,
    mutations: list[Mutation],
) -> None:
    """Find iterator/generator type names and generate swap mutations."""
    if isinstance(node, Leaf):
        if node.type == "name" and node.value in TARGET_NAMES:
            parent = node.parent
            has_trailer = False
            trailer_code = ""
            params: list[str] = []

            if parent is not None and isinstance(parent, BaseNode):
                idx = parent.children.index(node)
                if idx + 1 < len(parent.children):
                    next_child = parent.children[idx + 1]
                    if (
                        isinstance(next_child, BaseNode)
                        and next_child.type == "trailer"
                    ):
                        has_trailer = True
                        trailer_code = _node_code(next_child)
                        params = _extract_params(next_child)

            name = node.value
            line = node.start_pos[0]
            col = node.start_pos[1]

            if has_trailer:
                original_full = _node_code(node) + trailer_code
                _add_subscripted_mutations(
                    name, params, original_full, line, col, mutations
                )
            else:
                # Bare form — simple name swaps
                for target in BARE_SWAPS.get(name, []):
                    mutations.append(
                        Mutation(
                            file="",
                            operator="SwapIteratorGenerator",
                            line=line,
                            col=col,
                            original=name,
                            mutated=target,
                            description=f"Swap {name} → {target}",
                        )
                    )
            return

    if isinstance(node, BaseNode):
        for child in node.children:
            _find_iterator_generator(child, mutations)


def _add_subscripted_mutations(
    name: str,
    params: list[str],
    original_full: str,
    line: int,
    col: int,
    mutations: list[Mutation],
) -> None:
    """Add mutations for subscripted iterator/generator types."""
    swaps: list[tuple[str, str]] = []

    if name == "Iterator":
        # Iterator[Y] -> Generator[Y, None, None]
        yield_type = params[0] if params else ""
        swaps.append(("Generator", f"Generator[{yield_type}, None, None]"))
        # Iterator[Y] -> Iterable[Y]
        swaps.append(("Iterable", f"Iterable[{yield_type}]"))

    elif name == "Generator":
        # Generator[Y, S, R] -> Iterator[Y]
        yield_type = params[0] if params else ""
        swaps.append(("Iterator", f"Iterator[{yield_type}]"))

    elif name == "AsyncIterator":
        # AsyncIterator[Y] -> AsyncGenerator[Y, None]
        yield_type = params[0] if params else ""
        swaps.append(("AsyncGenerator", f"AsyncGenerator[{yield_type}, None]"))
        # AsyncIterator[Y] -> AsyncIterable[Y]
        swaps.append(("AsyncIterable", f"AsyncIterable[{yield_type}]"))

    elif name == "AsyncGenerator":
        # AsyncGenerator[Y, S] -> AsyncIterator[Y]
        yield_type = params[0] if params else ""
        swaps.append(("AsyncIterator", f"AsyncIterator[{yield_type}]"))

    elif name == "Iterable":
        # Iterable[Y] -> Iterator[Y]
        yield_type = params[0] if params else ""
        swaps.append(("Iterator", f"Iterator[{yield_type}]"))

    elif name == "AsyncIterable":
        # AsyncIterable[Y] -> AsyncIterator[Y]
        yield_type = params[0] if params else ""
        swaps.append(("AsyncIterator", f"AsyncIterator[{yield_type}]"))

    for target_name, mutated in swaps:
        mutations.append(
            Mutation(
                file="",
                operator="SwapIteratorGenerator",
                line=line,
                col=col,
                original=original_full,
                mutated=mutated,
                description=f"Swap {name} → {target_name}",
            )
        )
