"""Library plugins: library-specific mutation rules on top of the core operators."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from typemut.discovery import AnnotationNode
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.plugins.sqlalchemy import SQLAlchemyPlugin
from typemut.registry import Registry

logger = logging.getLogger(__name__)

PLUGINS: dict[str, type[Plugin]] = {
    SQLAlchemyPlugin.name: SQLAlchemyPlugin,
}


def get_plugins(names: Sequence[str]) -> list[Plugin]:
    """Instantiate plugins by name, in config order.

    Unknown names are logged as a warning and skipped, so a typo in the
    config does not abort the whole run.
    """
    unknown = [name for name in names if name not in PLUGINS]
    if unknown:
        logger.warning(
            "Skipping unknown plugin(s): %s. Available plugins: %s",
            ", ".join(unknown),
            ", ".join(sorted(PLUGINS)),
        )
    return [PLUGINS[name]() for name in names if name in PLUGINS]


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
