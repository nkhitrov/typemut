"""The fallback plugin for type checker commands typemut does not recognise."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from typemut.checkers.base import Diagnostic, ErrorFiles, TypeChecker
from typemut.checkers.mypy import FALSE_KILL_CODES

# A mypy-style ``[code]`` at the end of any line.
_ERROR_CODE_RE: Final = re.compile(r"\[(\w[\w-]*)\]\s*$")


class GenericChecker(TypeChecker):
    """Any command (``make typecheck``, a script): mypy-style codes, nothing else.

    Error codes are read from ``[code]`` at the end of any output line, so
    false kills are detected as for mypy. The files with errors and their
    dependencies are unknown, so results are never reused. The version is
    only known from ``checker-version-command``.
    """

    name = "generic"
    false_kill_codes = FALSE_KILL_CODES
    traces_dependencies = False

    def parse_output(self, output: str) -> Iterable[Diagnostic]:
        """One diagnostic per line ending with ``[code]``; the file is unknown."""
        return [
            Diagnostic("", match.group(1))
            for line in output.splitlines()
            if (match := _ERROR_CODE_RE.search(line)) is not None
        ]

    def error_files(self, stdout: str, stderr: str, root: Path) -> ErrorFiles:
        """None known: the output format is not known."""
        return ErrorFiles(frozenset())

    def dependencies(self, files: Iterable[str], root: Path) -> Iterable[str] | None:
        """Unknown, so no result may be reused."""
        return None
