"""WidenType operator."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry

# This operator targets user-defined classes from the project's class
# hierarchy (via Registry), not standard library types. The Registry resolves
# the annotation's name through the imports of the annotated file and tells
# how to write the base there, with the import line it needs, if any.

# Bases that carry no useful interface of their own: widening to them is
# either invalid as a type (Generic, Protocol, NamedTuple, TypedDict) or
# strips every member (object, ABC), so the mutant is trivially killed.
SKIPPED_BASES = frozenset(("object", "ABC", "Generic", "Protocol", "NamedTuple", "TypedDict"))


class WidenType(TypeMutationOperator):
    """Replaces a class in an annotation with its first base class.

    Only names that are a whole type are widened: not the parts of a dotted
    name, not call arguments (``Depends(Service)``) and not the values of a
    ``Literal[...]``. ``Child[int]`` is widened to ``Base`` when the class
    definition does not pass type arguments to its base, otherwise skipped.
    """

    name = "WidenType"
    config_key = "widen-type"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        mutations: list[Mutation] = []
        self._find_widenable_names(node, registry, mutations)
        return mutations

    def _find_widenable_names(
        self,
        node: BaseNode | Leaf,
        registry: Registry,
        mutations: list[Mutation],
    ) -> None:
        """Recursively find the class names that can be widened to their base class."""
        if isinstance(node, Leaf):
            if node.type == "name":
                self._widen(node, node, registry, mutations)
            return
        if node.type not in {"atom_expr", "power"}:
            for child in node.children:
                self._find_widenable_names(child, registry, mutations)
            return
        head, trailers = node.children[0], node.children[1:]
        subscripts = [t for t in trailers if t.get_first_leaf().value == "["]
        if len(trailers) == 1 and subscripts and head.type == "name":
            self._widen(head, node, registry, mutations)
        dotted = self._dotted_head(node)
        if dotted is not None and dotted.rpartition(".")[2] == "Literal":
            return  # values, not types
        for subscript in subscripts:
            self._find_widenable_names(subscript, registry, mutations)

    def _widen(
        self,
        name: Leaf,
        node: BaseNode | Leaf,
        registry: Registry,
        mutations: list[Mutation],
    ) -> None:
        """Widen the class *name*, replacing *node* (the name, maybe subscripted)."""
        widening = registry.widening(name.value)
        if widening is None or widening.qualified.rpartition(".")[2] in SKIPPED_BASES:
            return
        # ``class Child(Base[T])``: the arguments of Child[...] would not map to Base's.
        if node is not name and widening.subscripted:
            return
        original = self._node_code(node)
        mutations.append(
            Mutation(
                file="",
                operator="WidenType",
                line=node.start_pos[0],
                col=node.start_pos[1],
                original=original,
                mutated=widening.name,
                description=f"Widen {original} → {widening.name}",
                required_import=widening.required_import,
            )
        )
