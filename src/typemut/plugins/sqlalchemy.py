"""SQLAlchemy 2.0 plugin: mutate the type inside ``Mapped[...]``.

SQLAlchemy reads ``Mapped[X]`` at runtime: X decides the column type (via the
type annotation map), its nullability (``X | None``), and for relationships
the target class and the collection class. The core operators know nothing
about this, which gives noise:

- ``Mapped[int]`` -> ``Mapped[int] | None`` (AddOptional on the wrapper) is not
  a nullable column; the nullable column is ``Mapped[int | None]``.
- ``Mapped[str | None]`` is never mutated by RemoveOptional, because the union
  is nested inside the wrapper.
- ``Mapped[list[X]]`` -> ``Mapped[Sequence[X]]`` passes mypy but is invalid for
  SQLAlchemy, which needs a concrete column type or collection class.
- ``Mapped[UserDB]`` -> ``Mapped[BaseDB]`` on a relationship retargets it to
  the declarative base, which is not a mapped class.

The plugin runs the core operators on the type inside ``Mapped[...]`` (also
inside a quoted forward reference, ``Mapped["UserDB | None"]``) and drops
the mutations above.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, AnnotationNode, discover_annotations
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry

MAPPED = "Mapped"

# Always relationship collections: ``WriteOnlyMapped[X]`` means "a collection
# of X". None of the core mutations is valid for them (``X | None`` members,
# widening the target class), so they get no mutations at all.
COLLECTION_WRAPPERS = frozenset(("WriteOnlyMapped", "DynamicMapped"))

WRAPPERS = COLLECTION_WRAPPERS | {MAPPED}

RELATIONSHIP_FACTORIES = frozenset(("relationship", "dynamic_loader"))

# A single string literal, and implicitly concatenated string literals.
STRING_TYPES = frozenset(("string", "strings"))
QUOTES = frozenset(("'", '"'))

# Prefix put in front of a forward reference to parse it as an annotation.
FORWARD_REF_PREFIX = "_: "


class SQLAlchemyPlugin(Plugin):
    name = "sqlalchemy"

    def find_mutations(
        self,
        annotation: AnnotationNode,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
    ) -> list[Mutation] | None:
        """Mutate the type inside ``Mapped[...]``; leave other annotations to the core."""
        subscript = _subscript(annotation.node)
        if (
            annotation.context == AnnotationContext.TYPEVAR
            or subscript is None
            or subscript[0] not in WRAPPERS
        ):
            return None
        wrapper, inner = subscript
        if wrapper in COLLECTION_WRAPPERS or inner is None:
            return []

        rules = _Rules(
            context=annotation.context,
            operators=operators,
            registry=registry,
            relationship=_is_relationship(annotation.node),
        )
        if inner.type in STRING_TYPES:
            return _forward_ref_mutations(inner, rules)
        return rules.mutations(inner)


class _Rules:
    """Core operators applied to the type inside ``Mapped[...]``, minus invalid mutations."""

    def __init__(
        self,
        context: AnnotationContext,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
        *,
        relationship: bool,
    ) -> None:
        self.context = context
        self.operators = operators
        self.registry = registry
        self.relationship = relationship

    def mutations(self, inner: BaseNode | Leaf) -> list[Mutation]:
        found: list[Mutation] = []
        for op in self.operators:
            found.extend(op.find_mutations(inner, self.context, self.registry))
        return [mutation for mutation in found if self._is_valid(mutation, inner)]

    def _is_valid(self, mutation: Mutation, inner: BaseNode | Leaf) -> bool:
        at_top = (mutation.line, mutation.col) == inner.start_pos
        if mutation.operator == "WidenContainerType":
            # The top-level type is the column type / collection class:
            # SQLAlchemy needs a concrete class there, not an ABC.
            return not at_top
        if not self.relationship:
            return True
        if mutation.operator == "WidenType":
            # Relationship targets must be mapped classes.
            return False
        if mutation.operator == "AddOptional":
            # A collection relationship is never None, it is an empty collection.
            return _subscript(inner) is None
        return True


def _forward_ref_mutations(string: BaseNode | Leaf, rules: _Rules) -> list[Mutation]:
    """Mutate the annotation inside a quoted forward reference like ``"UserDB | None"``."""
    if not isinstance(string, Leaf):
        return []
    quote = string.value[0]
    if quote not in QUOTES or string.value.startswith(quote * 3):
        return []
    content = string.value[1:-1]
    parsed = discover_annotations(
        Path("<forward-ref>"), source=f"{FORWARD_REF_PREFIX}{content}\n", skip_comments=[]
    )
    if len(parsed) != 1:
        return []

    mutations: list[Mutation] = []
    for mutation in rules.mutations(parsed[0].node):
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


def _subscript(node: BaseNode | Leaf) -> tuple[str, BaseNode | Leaf | None] | None:
    """Split ``Name[arg]`` / ``module.Name[arg]`` into (Name, arg).

    arg is None when the subscript has several arguments.
    """
    target = _trailer_target(node, "[")
    if target is None:
        return None
    name, trailer = target
    arg = trailer.children[1]
    if isinstance(arg, BaseNode) and arg.type == "subscriptlist":
        return name, None
    return name, arg


def _is_relationship(annotation: BaseNode | Leaf) -> bool:
    """Check whether the annotated attribute is assigned a ``relationship(...)``."""
    annassign = annotation.parent
    if annassign is None or annassign.type != "annassign":
        return False
    value = annassign.children[-1]
    if value is annotation:
        return False
    target = _trailer_target(value, "(")
    return target is not None and target[0] in RELATIONSHIP_FACTORIES


def _trailer_target(node: BaseNode | Leaf, bracket: str) -> tuple[str, BaseNode] | None:
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
