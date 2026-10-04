"""The pyright (and basedpyright) type checker plugins."""

from __future__ import annotations

import re
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Final

from typemut.checkers.base import Diagnostic, TypeChecker

# Rule of an error pyright reports without one (syntax errors).
NO_RULE: Final = "<no-rule>"

FALSE_KILL_RULES: Final[AbstractSet[str]] = frozenset(
    {
        "reportUndefinedVariable",  # "Sequence" is not defined
        "reportInvalidTypeForm",  # Variable not allowed in type expression
        NO_RULE,  # syntax error in mutated code
    }
)

# ``  /abs/path.py:line:col - severity: message``; the message may continue
# on further, more indented lines, the last of which ends with ``(rule)``.
_DIAGNOSTIC_RE: Final = re.compile(
    r"^\s*(?P<path>.+?):\d+:\d+ - (?P<severity>error|warning|information): "
)
_RULE_RE: Final = re.compile(r"\((?P<rule>report\w+)\)\s*$")

CONFIG_FILES: Final = ("pyrightconfig.json", "pyproject.toml")


class PyrightChecker(TypeChecker):
    """pyright: ``path:line:col - error: message (reportRule)`` output."""

    name = "pyright"
    executables = frozenset({"pyright"})
    false_kill_codes = FALSE_KILL_RULES

    def parse_output(self, output: str) -> list[Diagnostic]:
        """Errors (not warnings or information) in pyright's output, by rule."""
        diagnostics: list[Diagnostic] = []
        # (path, severity, last line) of the diagnostic being read
        current: tuple[str, str, str] | None = None
        for line in output.splitlines():
            match = _DIAGNOSTIC_RE.match(line)
            if match is None and current is not None and line[:1].isspace():
                current = (current[0], current[1], line)
                continue
            if current is not None:
                diagnostics.extend(self._errors(*current))
            current = None if match is None else (match["path"], match["severity"], line)
        if current is not None:
            diagnostics.extend(self._errors(*current))
        return diagnostics

    def config_files(self, root: Path) -> list[Path]:
        """``--project`` and the config files pyright looks for in *root*."""
        files = [*self._explicit_config(root), *(root / name for name in CONFIG_FILES)]
        return [file for file in dict.fromkeys(files) if file.is_file()]

    def _explicit_config(self, root: Path) -> list[Path]:
        project = self._option(("-p", "--project"))
        if project is None:
            return []
        path = root / project
        return [path / "pyrightconfig.json" if path.is_dir() else path]

    def _errors(self, path: str, severity: str, last_line: str) -> list[Diagnostic]:
        """The diagnostic as an error with its rule, or nothing if it is not an error."""
        if severity != "error":
            return []
        rule = _RULE_RE.search(last_line)
        return [Diagnostic(path, NO_RULE if rule is None else rule["rule"])]


class BasedPyrightChecker(PyrightChecker):
    """basedpyright, a pyright fork with the same output format."""

    name = "basedpyright"
    executables = frozenset({"basedpyright"})
