"""Library plugins: library-specific mutation rules on top of the core operators."""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping
from importlib import metadata

from typemut.discovery import AnnotationNode
from typemut.ignore import IgnoredTypes
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.plugins.fastapi import FastAPIPlugin
from typemut.plugins.sqlalchemy import SQLAlchemyPlugin
from typemut.registry import Registry

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "typemut.plugins"

BUILTIN_PLUGINS: Mapping[str, type[Plugin]] = {
    FastAPIPlugin.name: FastAPIPlugin,
    SQLAlchemyPlugin.name: SQLAlchemyPlugin,
}


class PluginRegistry:
    """Plugins available by name for the ``plugins`` config option."""

    def __init__(self, plugins: Mapping[str, type[Plugin]] = BUILTIN_PLUGINS) -> None:
        self._plugins = dict(plugins)

    @classmethod
    def discover(cls, entry_points: Iterable[metadata.EntryPoint] | None = None) -> PluginRegistry:
        """Built-in plugins plus those installed under the ``typemut.plugins`` entry point group.

        An entry point names a :class:`Plugin` subclass, e.g. in ``pyproject.toml``::

            [project.entry-points."typemut.plugins"]
            django = "typemut_django:DjangoPlugin"

        Entry points that fail to load or are not plugins are logged and skipped.
        """
        if entry_points is None:
            entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
        plugins = dict(BUILTIN_PLUGINS)
        for entry_point in entry_points:
            plugin = cls._load_plugin(entry_point)
            if plugin is not None:
                plugins[entry_point.name] = plugin
        return cls(plugins)

    def get(self, names: Iterable[str]) -> Collection[Plugin]:
        """Instantiate plugins by name, in config order.

        Unknown names are logged as a warning and skipped, so a typo in the
        config does not abort the whole run.
        """
        plugins: list[Plugin] = []
        unknown: list[str] = []
        for name in names:
            plugin = self._plugins.get(name)
            if plugin is None:
                unknown.append(name)
            else:
                plugins.append(plugin())
        if unknown:
            logger.warning(
                "Skipping unknown plugin(s): %s. Available plugins: %s",
                ", ".join(unknown),
                ", ".join(sorted(self._plugins)),
            )
        return plugins

    @staticmethod
    def _load_plugin(entry_point: metadata.EntryPoint) -> type[Plugin] | None:
        try:
            loaded = entry_point.load()
        except Exception:
            logger.warning("Skipping plugin %r: failed to load", entry_point.name, exc_info=True)
            return None
        if not isinstance(loaded, type) or not issubclass(loaded, Plugin):
            logger.warning(
                "Skipping plugin %r: %s is not a typemut Plugin subclass",
                entry_point.name,
                entry_point.value,
            )
            return None
        return loaded


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
