"""The mypy type checker plugin."""

from __future__ import annotations

import configparser
import logging
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from typemut.checkers.base import Diagnostic, TypeChecker

logger = logging.getLogger(__name__)

# mypy error codes that indicate the mutated code is broken (missing import,
# syntax error, invalid type) rather than a genuine type-system kill.
FALSE_KILL_CODES: Final = frozenset(
    {
        "name-defined",  # Name "Sequence" is not defined
        "syntax",  # Syntax error in mutated code
        "valid-type",  # Not valid as a type
    }
)

# Code of an error mypy printed without one (``--hide-error-codes``).
NO_CODE: Final = "<no-code>"

# ``path:line[:col[:end_line:end_col]]: severity: message  [code]``
_HEADER_RE: Final = re.compile(
    r"^(?P<path>.+?\.pyi?):\d+(?::\d+){0,3}: (?P<severity>error|note): "
    r".*?(?:  \[(?P<code>[\w-]+)\])?\s*$"
)
# ``--pretty`` wraps long messages: the code ends a later, unindented line.
_WRAPPED_CODE_RE: Final = re.compile(r"(?:^|  )\[(?P<code>[\w-]+)\]\s*$")

# Config files in the order mypy looks for them.
CONFIG_FILES: Final = ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg")
DEFAULT_CACHE_DIR: Final = ".mypy_cache"
# ``$NAME`` or ``${NAME}`` in a path, expanded like ``os.path.expandvars``.
_VARIABLE_RE: Final = re.compile(r"\$(?:(?P<name>\w+)|\{(?P<braced>[^}]*)\})")


@dataclass
class _Message:
    """A message header line and the unindented lines ``--pretty`` wrapped it onto."""

    header: re.Match[str]
    wrapped: list[str] = field(default_factory=list)


class MypyChecker(TypeChecker):
    """mypy (and dmypy): ``path:line: error: message  [code]`` output."""

    name = "mypy"
    executables = frozenset({"mypy", "dmypy"})
    false_kill_codes = FALSE_KILL_CODES
    config_names = CONFIG_FILES

    def parse_output(self, output: str) -> Iterable[Diagnostic]:
        """Errors (not notes) in mypy's output, also with ``--pretty`` wrapping."""
        return [
            diagnostic for message in self._messages(output) for diagnostic in self._errors(message)
        ]

    def cache_paths(self, root: Path) -> Iterable[Path]:
        """mypy's cache directory, if it is inside *root*.

        Taken from ``--cache-dir``, ``MYPY_CACHE_DIR``, ``cache_dir`` in the
        config file, or the default ``.mypy_cache``, in that order, with
        ``~`` and ``$VAR`` expanded in the checker's environment, as mypy does.
        """
        project = root.resolve()
        path = (root / self._cache_dir(root)).resolve()
        if not path.is_relative_to(project):
            logger.warning("mypy cache %s is outside the project %s; not using it", path, project)
            return []
        return [root / path.relative_to(project)]

    def worktree_cache_paths(self, root: Path) -> Iterable[Path]:
        """mypy's cache directory if it is relative, so each worktree resolves its own copy.

        mypy in a worktree reads an absolute cache directory (from any source)
        from the same place as in *root*, so all workers share that one
        cache and a copy would never be read.
        """
        cache_dir = self._cache_dir(root)
        if Path(cache_dir).is_absolute():
            logger.warning(
                "mypy cache %s is an absolute path: parallel workers share it "
                "instead of getting their own copy",
                cache_dir,
            )
            return []
        return self.cache_paths(root)

    def _cache_dir(self, root: Path) -> str:
        """The configured cache directory, expanded, possibly relative to *root*."""
        return self._expand_path(
            self._command.option(("--cache-dir",))
            or self._environment().get("MYPY_CACHE_DIR")
            or self._configured_cache_dir(root)
            or DEFAULT_CACHE_DIR,
        )

    def _expand_path(self, path: str) -> str:
        """*path* with ``~`` and then ``$VAR`` expanded in the checker's environment."""
        home = self._environment().get("HOME")
        if home is not None and (path == "~" or path.startswith("~/")):
            expanded = home + path[1:]
        else:
            try:
                expanded = str(Path(path).expanduser())
            except RuntimeError:  # an unknown user (``~nobody``)
                expanded = path
        return _VARIABLE_RE.sub(self._variable, expanded)

    def _variable(self, match: re.Match[str]) -> str:
        """The value of the variable *match* names; the match itself if it is not set."""
        name = match["name"] or match["braced"]
        return self._environment().get(name, match.group())

    def _messages(self, output: str) -> Iterable[_Message]:
        """The messages in *output*, with the lines they were wrapped onto."""
        messages: list[_Message] = []
        continues = False
        for line in output.splitlines():
            header = _HEADER_RE.match(line)
            if header is not None:
                messages.append(_Message(header))
                continues = True
            elif continues and line[:1].strip():
                messages[-1].wrapped.append(line)
            else:
                continues = False
        return messages

    def _errors(self, message: _Message) -> Iterable[Diagnostic]:
        """The message as an error with its code, or nothing if it is a note."""
        header = message.header
        if header["severity"] != "error":
            return []
        wrapped_codes = (_WRAPPED_CODE_RE.search(line) for line in message.wrapped)
        codes = [header["code"], *(match["code"] for match in wrapped_codes if match)]
        code = next((code for code in codes if code is not None), NO_CODE)
        return [Diagnostic(header["path"], code)]

    def _explicit_config(self, root: Path) -> Path | None:
        """``--config-file``."""
        config = self._command.option(("--config-file",))
        return None if config is None else root / config

    def _configured_cache_dir(self, root: Path) -> str | None:
        """``cache_dir`` from the config file mypy uses."""
        explicit = self._explicit_config(root)
        candidates = [root / name for name in CONFIG_FILES] if explicit is None else [explicit]
        for file in candidates:
            section = self._mypy_section(file)
            if section is not None:
                cache_dir = section.get("cache_dir")
                return cache_dir if isinstance(cache_dir, str) else None
        return None

    def _mypy_section(self, file: Path) -> Mapping[str, object] | None:
        """The mypy settings in *file*, or None if it has none (or does not exist)."""
        if not file.is_file():
            return None
        if file.suffix == ".toml":
            try:
                data = tomllib.loads(file.read_text())
            except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
                return None
            tool = data.get("tool")
            section = tool.get("mypy") if isinstance(tool, dict) else None
            return section if isinstance(section, dict) else None
        # Like mypy, without ``%`` interpolation: values are often regexes.
        parser = configparser.RawConfigParser()
        try:
            parser.read(file)
        except (configparser.Error, UnicodeDecodeError):
            return None
        return dict(parser["mypy"]) if parser.has_section("mypy") else None
