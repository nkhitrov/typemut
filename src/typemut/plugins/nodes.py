"""parso helpers shared by plugins."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf


def trailer_target(node: BaseNode | Leaf, bracket: str) -> tuple[str, BaseNode] | None:
    """For ``name[...]``/``a.name(...)`` return the name and the last trailer."""
    if not isinstance(node, BaseNode) or node.type not in {"atom_expr", "power"}:
        return None
    trailer = node.children[-1]
    if not isinstance(trailer, BaseNode) or trailer.type != "trailer":
        return None
    opening = trailer.children[0]
    if not isinstance(opening, Leaf) or opening.value != bracket:
        return None

    target = node.children[-2]
    if isinstance(target, BaseNode) and target.type == "trailer":
        # Attribute access: `.name`
        target = target.children[-1]
    if not isinstance(target, Leaf) or target.type != "name":
        return None
    return target.value, trailer
