"""Mutations of an annotation: plugins first, then the core operators with ignore rules."""

from __future__ import annotations

from collections.abc import Collection

from typemut.ignore import IgnoredTypes
from typemut.model import AnnotationNode, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry


class MutationFinder:
    """Finds the mutations of annotations with *operators*, *plugins* and ignore rules.

    The first plugin that claims an annotation decides its mutations;
    otherwise every operator runs on the annotation as is, except operators
    that ignore a type the annotation references (see ``typemut.ignore``).
    """

    def __init__(
        self,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
        plugins: Collection[Plugin] = (),
        ignored: IgnoredTypes | None = None,
    ) -> None:
        self._operators = operators
        self._registry = registry
        self._plugins = plugins
        self._ignored = ignored or IgnoredTypes()

    def find(self, annotation: AnnotationNode) -> list[Mutation]:
        """Return all mutations for an annotation."""
        for plugin in self._plugins:
            claimed = plugin.find_mutations(annotation, self._operators, self._registry)
            if claimed is not None:
                return claimed
        return self._core_mutations(annotation)

    def _core_mutations(self, annotation: AnnotationNode) -> list[Mutation]:
        mutations: list[Mutation] = []
        for op in self._operators:
            if self._ignored.is_ignored(annotation, op.config_key):
                continue
            found = op.find_mutations(annotation.node, annotation.context, self._registry)
            mutations.extend(
                m for m in found if not self._ignored.drops(m, annotation, op.config_key)
            )
        return mutations
