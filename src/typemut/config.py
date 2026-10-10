"""TOML config parsing for typemut."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Container, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# Operator keys under [typemut.operators] and [typemut.ignore-types].
OPERATOR_KEYS: tuple[str, ...] = (
    "remove-union-member",
    "remove-literal-member",
    "widen-type",
    "remove-optional",
    "add-optional",
    "widen-container-type",
    "swap-iterator-generator",
    "typevar-variance",
)

# Results database, relative to the project root.
DEFAULT_DB_PATH = "typemut.sqlite"

# Key under [typemut.ignore-types] that applies to every operator.
ALL_OPERATORS = "all"

# Files whose change invalidates every cached result: the project's lockfiles.
DEFAULT_CACHE_KEY_FILES: Final = ("uv.lock", "poetry.lock", "requirements*.txt")


@dataclass
class OperatorsConfig:
    remove_union_member: bool = True
    remove_literal_member: bool = True
    widen_type: bool = True
    remove_optional: bool = True
    add_optional: bool = True
    widen_container_type: bool = True
    swap_iterator_generator: bool = True
    typevar_variance: bool = True

    def disabled_operators(self) -> Container[str]:
        """Config keys of the operators switched off."""
        return {key for key in OPERATOR_KEYS if not getattr(self, key.replace("-", "_"))}


@dataclass
class Config:
    module_path: str = "src"
    test_command: str = "mypy src/"
    timeout: int = 30
    excluded_modules: list[str] = field(default_factory=list)
    skip_comments: list[str] = field(default_factory=lambda: ["type: ignore", "pragma: no mutate"])
    operators: OperatorsConfig = field(default_factory=OperatorsConfig)
    plugins: list[str] = field(default_factory=list)
    # {operator key or "all": [qualified type name patterns]}
    ignore_types: dict[str, list[str]] = field(default_factory=dict)
    db_path: str = DEFAULT_DB_PATH
    # type checker plugin name; None detects it from test_command
    checker: str | None = None
    checker_version_command: str | None = None
    # reuse kills of earlier runs while the files they depend on are unchanged
    incremental: bool = False  # pragma: no mutate (truth-tested)
    # seconds after which no new mutant is started; None: no limit
    max_duration: float | None = None
    # glob patterns of files (relative to the project root) the cache depends on
    cache_key_files: Iterable[str] = DEFAULT_CACHE_KEY_FILES


class ConfigLoader:
    """Reads a :class:`Config` from the ``[typemut]`` table of a TOML file.

    Invalid option values are logged and replaced by their defaults.
    """

    def load(self, path: Path) -> Config:
        """Load config from a TOML file."""
        text = path.read_text()
        raw = tomllib.loads(text)

        section = raw.get("typemut", {})
        ops_raw = section.pop("operators", {})

        operators = OperatorsConfig(
            **{key.replace("-", "_"): ops_raw.get(key, True) for key in OPERATOR_KEYS}
        )

        return Config(
            module_path=section.get("module-path", "src"),
            test_command=section.get("test-command", "mypy src/"),
            timeout=section.get("timeout", 30),
            excluded_modules=section.get("excluded-modules", []),
            skip_comments=section.get("skip-comments", ["type: ignore", "pragma: no mutate"]),
            operators=operators,
            plugins=self._parse_plugins(section.get("plugins", [])),
            ignore_types=self._parse_ignore_types(section.get("ignore-types", {})),
            db_path=section.get("db", DEFAULT_DB_PATH),
            checker=self._optional_string(section.get("checker"), "checker"),
            checker_version_command=self._optional_string(
                section.get("checker-version-command"), "checker-version-command"
            ),
            incremental=self._bool(section.get("incremental", False), "incremental"),
            max_duration=self._max_duration(section.get("max-duration")),
            cache_key_files=self._cache_key_files(section.get("cache-key-files")),
        )

    def _cache_key_files(self, raw: object) -> Iterable[str]:
        """Validate ``cache-key-files``; the default lockfiles if unset or invalid."""
        if raw is None:
            return DEFAULT_CACHE_KEY_FILES
        patterns = self._string_list(raw, "cache-key-files")
        if patterns is None:
            return DEFAULT_CACHE_KEY_FILES
        return [pattern for pattern in patterns if self._usable_key_file_pattern(pattern)]

    def _usable_key_file_pattern(self, pattern: str) -> bool:  # pragma: no mutate (truth-tested)
        """Whether a ``cache-key-files`` *pattern* can be globbed; warn if not."""
        if not pattern.strip():
            logger.warning("Ignoring empty 'cache-key-files' pattern %r", pattern)
            return False
        if Path(pattern).is_absolute():
            logger.warning(
                "Ignoring absolute 'cache-key-files' pattern %r: "
                "patterns are relative to the project root",
                pattern,
            )
            return False
        return True

    def _bool(self, raw: object, option: str) -> bool:
        """Return *raw* if it is a boolean, else warn and return False."""
        if isinstance(raw, bool):
            return raw
        logger.warning("Ignoring invalid %r option %r: expected true or false", option, raw)
        return False

    def _max_duration(self, raw: object) -> float | None:
        """Validate ``max-duration``: a positive number of seconds."""
        if raw is None:
            return None
        if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
            return float(raw)
        logger.warning(
            "Ignoring invalid 'max-duration' option %r: expected a positive number of seconds", raw
        )
        return None

    def _optional_string(self, raw: object, option: str) -> str | None:
        """Return *raw* if it is a string or None, else warn and return None."""
        if raw is None or isinstance(raw, str):
            return raw
        logger.warning("Ignoring invalid %r option %r: expected a string", option, raw)
        return None

    def _parse_plugins(self, raw: object) -> list[str]:
        """Validate the ``plugins`` option; warn and ignore invalid values."""
        return self._string_list(raw, "plugins") or []

    def _parse_ignore_types(self, raw: object) -> dict[str, list[str]]:
        """Validate ``[typemut.ignore-types]``; warn about and skip invalid entries."""
        if not isinstance(raw, dict):
            logger.warning("Ignoring invalid 'ignore-types' option %r: expected a table", raw)
            return {}
        valid_keys = (ALL_OPERATORS, *OPERATOR_KEYS)
        ignore_types: dict[str, list[str]] = {}
        for key, value in raw.items():
            if key not in valid_keys:
                logger.warning(
                    "Ignoring unknown operator %r in 'ignore-types'. Valid keys: %s",
                    key,
                    ", ".join(valid_keys),
                )
                continue
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
