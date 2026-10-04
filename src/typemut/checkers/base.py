"""The base class of type checker plugins."""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Collection, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from typemut.checkers.graph import ImportGraph
from typemut.runner import CommandRunner, Outcome, ShellRunner

logger = logging.getLogger(__name__)

VERSION_RE: Final = re.compile(r"\d+\.\d+\.\d+\S*")

# Seconds to wait for the version command.
VERSION_TIMEOUT: Final = 60

# Shell operators that start a new command in a test command line.
_COMMAND_SEPARATORS: Final = frozenset({"&&", "||", ";", "|", "&"})


@dataclass(frozen=True)
class Diagnostic:
    """A type error: the file the checker reported it in and its error code."""

    path: str
    code: str


@dataclass(frozen=True)
class ErrorFiles:
    """Files a type checker reported errors in.

    *paths* are project files relative to the project root; *external* is
    set when some errors are in files outside the project root.
    """

    paths: frozenset[str]
    external: bool = False


class TypeChecker:
    """What typemut knows about the type checker that ``test-command`` runs.

    A checker parses the command's output (error codes, files with errors),
    reports its version, and names the files its results depend on. The
    base class knows no output format; subclasses override
    :meth:`parse_output` and set :attr:`name`, :attr:`executables` and
    :attr:`false_kill_codes`.
    """

    # Name in the ``checker`` config option.
    name: ClassVar[str] = "base"
    # File names of the checker's executable, used to detect it in
    # ``test-command`` and to derive the version command.
    executables: ClassVar[AbstractSet[str]] = frozenset()
    # Error codes that mean the mutated code is broken (a missing import, a
    # syntax error) rather than caught by the type system.
    false_kill_codes: ClassVar[AbstractSet[str]] = frozenset()

    def __init__(
        self,
        test_command: str = "",
        version_command: str | None = None,
        runner: CommandRunner | None = None,
        graph: ImportGraph | None = None,
    ) -> None:
        self.test_command = test_command
        self.version_command = version_command
        self._runner = runner or ShellRunner()
        self._graph = graph or ImportGraph()

    @classmethod
    def runs(cls, test_command: str) -> bool:
        """Whether *test_command* starts this checker."""
        return cls._executable_index(cls._tokens(test_command)) is not None

    def version(self, root: Path) -> str | None:
        """The checker's version (``1.15.0``), or None if it cannot be found.

        Runs ``checker-version-command`` if configured, otherwise the
        ``test-command`` up to the checker's executable plus ``--version``
        (``uv run mypy --version``).
        """
        command = self.version_command or self._default_version_command()
        if command is None:
            return None
        result = self._runner.run(command, timeout=VERSION_TIMEOUT, cwd=root)
        if result.outcome is not Outcome.PASSED:
            logger.warning("Version command %r failed: %s", command, result.output.strip())
            return None
        match = VERSION_RE.search(result.stdout) or VERSION_RE.search(result.stderr)
        if match is None:
            logger.warning("No version number in the output of %r", command)
            return None
        return match.group()

    def is_false_kill(self, stdout: str, stderr: str) -> bool:
        """Whether a failed run reports errors, all of them from broken mutated code."""
        codes = {diagnostic.code for diagnostic in self.diagnostics(stdout, stderr)}
        return bool(codes) and codes <= self.false_kill_codes

    def diagnostics(self, stdout: str, stderr: str) -> list[Diagnostic]:
        """Errors in the output of a run, from both streams."""
        return [*self.parse_output(stdout), *self.parse_output(stderr)]

    def parse_output(self, output: str) -> list[Diagnostic]:
        """Errors in one output stream; the base class knows no format."""
        return []

    def error_files(self, stdout: str, stderr: str, root: Path) -> ErrorFiles:
        """Files with errors in the output of a run in *root*."""
        project = root.resolve()
        paths: set[str] = set()
        external = False
        for diagnostic in self.diagnostics(stdout, stderr):
            path = self._project_path(diagnostic.path, project)
            if path is None:
                external = True
            else:
                paths.add(path)
        return ErrorFiles(frozenset(paths), external)

    def config_files(self, root: Path) -> list[Path]:
        """Existing checker config files in *root* that can change its results."""
        return []

    def cache_paths(self, root: Path) -> list[Path]:
        """Checker cache directories inside *root* worth giving to workers."""
        return []

    def dependencies(self, files: Iterable[str], root: Path) -> set[str] | None:
        """*files* and the project files they import, relative to *root*.

        None means the checker cannot tell, so no result may be reused.
        """
        return self._graph.closure(files, root)

    def _default_version_command(self) -> str | None:
        """``test-command`` up to the checker's executable, plus ``--version``."""
        tokens = self._tokens(self.test_command)
        end = self._executable_index(tokens)
        if end is None:
            return None
        start = max(
            (index + 1 for index, token in enumerate(tokens[:end]) if token in _COMMAND_SEPARATORS),
            default=0,
        )
        return shlex.join([*tokens[start : end + 1], "--version"])

    def _option(self, names: Collection[str]) -> str | None:
        """The last value of a ``--name value`` or ``--name=value`` option of ``test-command``."""
        tokens = self._tokens(self.test_command)
        value: str | None = None
        for index, token in enumerate(tokens):
            name, equals, inline = token.partition("=")
            if name not in names:
                continue
            if equals:
                value = inline
            elif index + 1 < len(tokens):
                value = tokens[index + 1]
        return value

    def _project_path(self, path: str, project: Path) -> str | None:
        """*path* relative to the resolved *project* root, or None if outside it."""
        file = Path(path)
        if not file.is_absolute():
            file = project / file
        file = file.resolve()
        if not file.is_relative_to(project):
            return None
        return file.relative_to(project).as_posix()

    @classmethod
    def _executable_index(cls, tokens: list[str]) -> int | None:
        """Position of the checker's executable in the command's tokens."""
        for index, token in enumerate(tokens):
            if Path(token).name in cls.executables:
                return index
        return None

    @staticmethod
    def _tokens(command: str) -> list[str]:
        """Shell words of *command*, with operators such as ``&&`` as separate words."""
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            return list(lexer)
        except ValueError:
            return []
