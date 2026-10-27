"""Library plugins: library-specific mutation rules on top of the core operators."""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping
from importlib import metadata
from typing import Final

from typemut.config import EntrypointsConfig
from typemut.plugins import dmr, fastapi, faststream, pydantic, sqlalchemy, taskiq
from typemut.plugins.base import Plugin
from typemut.plugins.entrypoints import EntrypointsPlugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "typemut.plugins"

NO_ENTRYPOINTS: Final = EntrypointsConfig()

BUILTIN_PLUGINS: Mapping[str, type[Plugin]] = {
    plugin.name: plugin
    for plugin in (
        dmr.DmrPlugin,
        fastapi.FastAPIPlugin,
        faststream.FastStreamPlugin,
        pydantic.PydanticPlugin,
        sqlalchemy.SQLAlchemyPlugin,
        taskiq.TaskiqPlugin,
    )
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

    def get(
        self, names: Iterable[str], entrypoints: EntrypointsConfig = NO_ENTRYPOINTS
    ) -> Collection[Plugin]:
        """Instantiate plugins by name, in config order.

        Unknown names are logged as a warning and skipped, so a typo in the
        config does not abort the whole run. Configured *entrypoints* add an
        :class:`EntrypointsPlugin` in front: a handler's signature is skipped
        whatever library types it uses.
        """
        handlers = EntrypointsPlugin(entrypoints)
        plugins: list[Plugin] = [handlers] if handlers.configured() else []
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
