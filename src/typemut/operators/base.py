"""Abstract base for mutation operators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext
from typemut.nodes import NodeSource

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typemut.registry import Registry


@dataclass
class Mutation:
    file: str
    operator: str
    line: int
    col: int
    original: str
    mutated: str
    description: str
    # Full import line needed for the mutated type, e.g. "from abc import ABC".
    # None when no import is needed (builtins or already in scope).
    required_import: str | None = None


class TypeMutationOperator(NodeSource, ABC):
    name: str = ""
    # Key in [typemut.operators] / [typemut.ignore-types], e.g. "add-optional".
    config_key: str = ""

    @abstractmethod
    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Return all possible mutations for this annotation node."""
        ...

    def _is_qualified_name(self, leaf: Leaf) -> bool:
        """Check whether *leaf* is the attribute part of a dotted name (``module.name``)."""
        parent = leaf.parent
        return (
            parent is not None
            and parent.type == "trailer"
            and parent.children[0].type == "operator"
            and parent.children[0].get_code(include_prefix=False) == "."
        )

    def _union_members(self, node: BaseNode | Leaf) -> list[BaseNode | Leaf]:
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
        return [c for c in node.children if not (isinstance(c, Leaf) and c.value == "|")]

    def _type_params(self, trailer: BaseNode) -> list[str]:
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
                code = self._node_code(child)
                if child.type == "operator" and code.strip() == ",":
                    params.append("".join(current_parts).strip())
                    current_parts = []
                else:
                    current_parts.append(code)
            if current_parts:
                params.append("".join(current_parts).strip())
            return params

        # Single parameter
        return [self._node_code(content).strip()]
