"""parso node helpers shared by discovery, operators and plugins."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf


class NodeSource:
    """Mixin giving subclasses the exact source text and dotted names of parso nodes."""

    def _node_code(self, node: BaseNode | Leaf) -> str:
        """Get the exact source code text of a node, preserving whitespace."""
        code = node.get_code()
        # get_code() includes the prefix (leading whitespace) of the first leaf.
        # Strip it to get just the annotation text.
        first = node
        while hasattr(first, "children") and first.children:
            first = first.children[0]
        if hasattr(first, "prefix"):
            prefix = first.prefix
            if code.startswith(prefix):
                code = code[len(prefix) :]
        return code

    def _dotted_head(self, node: BaseNode) -> str | None:
        """Return ``orm.Mapped`` for ``orm.Mapped[...]``, None if not a name chain."""
        head = node.children[0]
        if (
            node.type not in {"atom_expr", "power"}
            or not isinstance(head, Leaf)
            or head.type != "name"
        ):
            return None
        parts = [head.value]
        for trailer in node.children[1:]:
            attribute = self._attribute_name(trailer)
            if attribute is None:
                break
            parts.append(attribute)
        return ".".join(parts)

    # parso's children are untyped, so a narrower parameter type would pass mypy too.
    def _attribute_name(self, node: BaseNode | Leaf) -> str | None:  # pragma: no mutate
        """Return ``x`` for a ``.x`` trailer, None for anything else."""
        if isinstance(node, Leaf) or node.type != "trailer":
            return None
        dot, name = node.children[0], node.children[-1]
        if isinstance(dot, Leaf) and dot.value == "." and isinstance(name, Leaf):
            return name.value
        return None
