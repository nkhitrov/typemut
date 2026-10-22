"""Mutations of an annotation: plugins first, then the core operators with ignore rules."""

from __future__ import annotations

from collections.abc import Collection

from typemut.hierarchy import ClassHierarchy
from typemut.ignore import IgnoredClasses, IgnoredTypes
from typemut.model import AnnotationNode, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry


class MutationFinder:
    """Finds the mutations of annotations with *operators*, *plugins* and ignore rules.

    The first plugin that claims an annotation decides its mutations;
    otherwise every operator runs on the annotation as is, except operators
    that ignore a type the annotation references or the class it is a field
    of (see ``typemut.ignore``).
    """

    def __init__(
        self,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
        plugins: Collection[Plugin] = (),
        ignored: IgnoredTypes | None = None,
        ignored_classes: IgnoredClasses | None = None,
    ) -> None:
        self._operators = operators
        self._registry = registry
        self._plugins = plugins
        self._ignored = ignored or IgnoredTypes()
        self._ignored_classes = ignored_classes or IgnoredClasses({}, ClassHierarchy())

    def find(self, annotation: AnnotationNode) -> list[Mutation]:
        """Return all mutations for an annotation."""
        # Operators and plugins resolve names through the annotated file's imports.
        registry = self._registry.in_file(annotation.file)
        for plugin in self._plugins:
            claimed = plugin.find_mutations(annotation, self._operators, registry)
            if claimed is not None:
                return claimed
        return self._core_mutations(annotation, registry)

    def _core_mutations(self, annotation: AnnotationNode, registry: Registry) -> list[Mutation]:
        mutations: list[Mutation] = []
        for op in self._operators:
            if self._ignored.is_ignored(annotation, op.config_key):
                continue
            if self._ignored_classes.is_ignored(annotation, op.config_key):
                continue
            found = op.find_mutations(annotation.node, annotation.context, registry)
            mutations.extend(
                m for m in found if not self._ignored.drops(m, annotation, op.config_key)
            )
        return mutations
