"""parso node helpers shared by discovery, operators and plugins."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf


class NodeSource:
    """Mixin giving subclasses the exact source text of parso nodes."""

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
