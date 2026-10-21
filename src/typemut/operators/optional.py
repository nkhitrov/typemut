"""RemoveOptional and AddOptional operators."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import ForwardRefs, TypeMutationOperator
from typemut.registry import Registry

# Type qualifiers: ``ClassVar[int] | None`` is not a type (mypy valid-type,
# TypeError at runtime), the optional value goes inside: ``ClassVar[int | None]``.
# That is a meaningful mutant for each of them: an optional class variable,
# final value, TypedDict value (the key stays (not) required / read-only) or
# dataclass init-only argument. A bare ``Final``/``ClassVar`` gets nothing.
QUALIFIERS = frozenset(("ClassVar", "Final", "Required", "NotRequired", "ReadOnly", "InitVar"))


class RemoveOptional(TypeMutationOperator):
    name = "RemoveOptional"
    config_key = "remove-optional"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Detect X | None and generate mutation removing None."""
        members = self._union_members(node)
        if len(members) < 2:
            return []

        none_indices = [
            i for i, m in enumerate(members) if isinstance(m, Leaf) and m.value == "None"
        ]
        if not none_indices:
            return []

        remaining = [m for i, m in enumerate(members) if i not in none_indices]
        if not remaining:
            return []

        remaining_codes = [self._node_code(m).strip() for m in remaining]
        mutated = " | ".join(remaining_codes)
        original = self._node_code(node)

        return [
            Mutation(
                file="",
                operator=self.name,
                line=node.start_pos[0],
                col=node.start_pos[1],
                original=original,
                mutated=mutated,
                description=f"Remove Optional (None) → {mutated}",
            )
        ]


class AddOptional(TypeMutationOperator):
    name = "AddOptional"
    config_key = "add-optional"

    def __init__(self, forward_refs: ForwardRefs | None = None) -> None:
        self._forward_refs = forward_refs or ForwardRefs()

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        """Add None to a type that doesn't already have it.

        Only applies to return types and class fields — adding None to
        parameters has low value since callers simply won't pass None.
        TypeVar declarations are skipped: ``TypeVar("T") | None`` is not a
        type annotation, and the checker error it causes is not a real kill.
        ``TypeAlias`` annotations are skipped for the same reason:
        ``TypeAlias | None`` is not a valid type.
        Quoted annotations and type qualifiers get None inside:
        ``'Foo'`` -> ``'Foo | None'``, ``ClassVar[int]`` -> ``ClassVar[int | None]``.
        """
        if context in {AnnotationContext.PARAMETER, AnnotationContext.TYPEVAR}:
            return []

        if self._forward_refs.is_quoted(node):
            return self._forward_refs.mutations(
                node, lambda inner: self.find_mutations(inner, context, registry)
            )

        code = self._node_code(node).strip()
        if code.partition("[")[0].rpartition(".")[2] in QUALIFIERS:
            return self._qualified_mutations(node, context, registry)
        return self._add_none(node, code)

    def _qualified_mutations(
        self, node: BaseNode | Leaf, context: AnnotationContext, registry: Registry
    ) -> list[Mutation]:
        """Add None to the type inside ``ClassVar[...]``; nothing for a bare ``ClassVar``."""
        trailer = node.children[-1] if isinstance(node, BaseNode) else None
        if trailer is None or trailer.type != "trailer" or trailer.children[0].value != "[":
            return []
        return self.find_mutations(trailer.children[1], context, registry)

    def _add_none(self, node: BaseNode | Leaf, code: str) -> list[Mutation]:
        """``code | None``, unless *code* is ``TypeAlias`` or already has None."""
        if code.rpartition(".")[2] == "TypeAlias" or self._contains_none(node):
            return []
        mutated = f"{code} | None"
        return [
            Mutation(
                file="",
                operator=self.name,
                line=node.start_pos[0],
                col=node.start_pos[1],
                original=code,
                mutated=mutated,
                description=f"Add Optional: {code} → {mutated}",
            )
        ]

    def _contains_none(self, node: BaseNode | Leaf) -> bool:
        """Check if a node contains None anywhere."""
        if isinstance(node, Leaf):
            return node.value == "None"
        return any(self._contains_none(child) for child in node.children)
