"""Abstract base for mutation operators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationFinder
from typemut.model import AnnotationContext, Mutation
from typemut.nodes import NodeSource
from typemut.registry import Registry

# A single string literal, and implicitly concatenated string literals.
STRING_TYPES = frozenset(("string", "strings"))
QUOTES = frozenset(("'", '"'))

# Prefix put in front of a forward reference to parse it as an annotation.
FORWARD_REF_PREFIX = "_: "


class ForwardRefs:
    """Mutates the annotation inside a quoted forward reference like ``'Foo | None'``.

    A mutation must stay inside the quotes: ``'Foo' | None`` passes the type
    checker but is ``str | None`` at runtime, which raises TypeError.
    """

    def __init__(self, finder: AnnotationFinder | None = None) -> None:
        # Parses the annotation inside the quotes.
        self._finder = finder or AnnotationFinder(skip_comments=())

    def is_quoted(self, node: BaseNode | Leaf) -> bool:
        """Whether *node* is a string literal used as an annotation."""
        return node.type in STRING_TYPES

    def mutations(
        self,
        string: BaseNode | Leaf,
        mutate: Callable[[BaseNode | Leaf], Iterable[Mutation]],
    ) -> list[Mutation]:
        """Apply *mutate* to the annotation inside *string*, re-quoting the results.

        Strings the checker would not read as one plain forward reference
        (triple-quoted, prefixed, implicitly concatenated, empty) get none.
        """
        if not isinstance(string, Leaf):
            return []
        quote = string.value[0]
        if quote not in QUOTES or string.value.startswith(quote * 3):
            return []
        content = string.value[1:-1]
        parsed = self._finder.find(Path("<forward-ref>"), source=f"{FORWARD_REF_PREFIX}{content}\n")
        if len(parsed) != 1:
            return []

        mutations: list[Mutation] = []
        for mutation in mutate(parsed[0].node):
            start = mutation.col - len(FORWARD_REF_PREFIX)
            end = start + len(mutation.original)
            mutated = content[:start] + mutation.mutated + content[end:]
            mutations.append(
                Mutation(
                    file=mutation.file,
                    operator=mutation.operator,
                    line=string.start_pos[0],
                    col=string.start_pos[1],
                    original=string.value,
                    mutated=f"{quote}{mutated}{quote}",
                    description=mutation.description,
                    required_import=mutation.required_import,
                )
            )
        return mutations


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

    def _union_members(self, node: BaseNode | Leaf) -> Collection[BaseNode | Leaf]:
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

    def _type_params(self, trailer: BaseNode) -> Sequence[str]:
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
