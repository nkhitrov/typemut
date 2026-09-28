"""TOML config parsing for typemut."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Key under [typemut.ignore-types] that applies to every operator.
ALL_OPERATORS = "all"


@dataclass
class Config:
    module_path: str = "src"
    test_command: str = "mypy src/"
    timeout: int = 30
    excluded_modules: list[str] = field(default_factory=list)
    skip_comments: list[str] = field(default_factory=lambda: ["type: ignore", "pragma: no mutate"])
    # {operator key: enabled}; operators not listed are enabled.
    operators: Mapping[str, bool] = field(default_factory=dict)
    plugins: list[str] = field(default_factory=list)
    # {operator key or "all": [qualified type name patterns]}
    ignore_types: dict[str, list[str]] = field(default_factory=dict)
    db_path: str = "typemut.sqlite"


class ConfigLoader:
    """Reads a :class:`Config` from the ``[typemut]`` table of a TOML file.

    Invalid option values are logged and replaced by their defaults.
    """

    def load(self, path: Path) -> Config:
        """Load config from a TOML file."""
        text = path.read_text()
        raw = tomllib.loads(text)

        section = raw.get("typemut", {})
        return Config(
            module_path=section.get("module-path", "src"),
            test_command=section.get("test-command", "mypy src/"),
            timeout=section.get("timeout", 30),
            excluded_modules=section.get("excluded-modules", []),
            skip_comments=section.get("skip-comments", ["type: ignore", "pragma: no mutate"]),
            operators=self._parse_operators(section.get("operators", {})),
            plugins=self._parse_plugins(section.get("plugins", [])),
            ignore_types=self._parse_ignore_types(section.get("ignore-types", {})),
            db_path=section.get("db", "typemut.sqlite"),
        )

    def _parse_plugins(self, raw: object) -> list[str]:
        """Validate the ``plugins`` option; warn and ignore invalid values."""
        return self._string_list(raw, "plugins") or []

    def _parse_operators(self, raw: object) -> dict[str, bool]:
        """Validate ``[typemut.operators]``; warn about and skip values that are not booleans.

        Operator keys are checked later, against the operators that are
        actually available (built-in and from plugins).
        """
        if not isinstance(raw, dict):
            logger.warning("Ignoring invalid 'operators' option %r: expected a table", raw)
            return {}
        operators: dict[str, bool] = {}
        for key, value in raw.items():
            if isinstance(value, bool):
                operators[key] = value
            else:
                logger.warning(
                    "Ignoring invalid 'operators.%s' option %r: expected true or false", key, value
                )
        return operators

    def _parse_ignore_types(self, raw: object) -> dict[str, list[str]]:
        """Validate ``[typemut.ignore-types]``; warn about and skip invalid entries.

        Operator keys are checked later, like those of ``[typemut.operators]``.
        """
        if not isinstance(raw, dict):
            logger.warning("Ignoring invalid 'ignore-types' option %r: expected a table", raw)
            return {}
        ignore_types: dict[str, list[str]] = {}
        for key, value in raw.items():
            patterns = self._string_list(value, f"ignore-types.{key}")
            if patterns is not None:
                ignore_types[key] = patterns
        return ignore_types

    def _string_list(self, raw: object, option: str) -> list[str] | None:
        """Return *raw* if it is a list of strings, else warn and return None."""
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            return raw
        logger.warning("Ignoring invalid %r option %r: expected a list of strings", option, raw)
        return None
