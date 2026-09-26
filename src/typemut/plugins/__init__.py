"""Library plugins: library-specific mutation rules on top of the core operators."""

from __future__ import annotations

from collections.abc import Sequence

from typemut.discovery import AnnotationNode
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.plugins.sqlalchemy import SQLAlchemyPlugin
from typemut.registry import Registry

PLUGINS: dict[str, type[Plugin]] = {
    SQLAlchemyPlugin.name: SQLAlchemyPlugin,
}


class UnknownPluginError(ValueError):
    """Raised when the config names a plugin that does not exist."""


def get_plugins(names: Sequence[str]) -> list[Plugin]:
    """Instantiate plugins by name, in config order."""
    unknown = [name for name in names if name not in PLUGINS]
    if unknown:
        available = ", ".join(sorted(PLUGINS))
        raise UnknownPluginError(
            f"Unknown plugin(s): {', '.join(unknown)}. Available plugins: {available}"
        )
    return [PLUGINS[name]() for name in names]


def find_mutations(
    annotation: AnnotationNode,
    operators: Sequence[TypeMutationOperator],
    registry: Registry,
    plugins: Sequence[Plugin] = (),
) -> list[Mutation]:
    """Return all mutations for an annotation.

    The first plugin that claims the annotation decides its mutations;
    otherwise every operator runs on the annotation as is.
    """
    for plugin in plugins:
        claimed = plugin.find_mutations(annotation, operators, registry)
        if claimed is not None:
            return claimed
    mutations: list[Mutation] = []
    for op in operators:
        mutations.extend(op.find_mutations(annotation.node, annotation.context, registry))
    return mutations
