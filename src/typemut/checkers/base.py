"""The base class of type checker plugins."""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from typemut.checkers.command import CommandLine
from typemut.checkers.graph import ImportGraph
from typemut.runner import CommandRunner, Outcome, ShellRunner

logger = logging.getLogger(__name__)

VERSION_RE: Final = re.compile(r"\d+\.\d+\.\d+\S*")

# Seconds to wait for the version command.
VERSION_TIMEOUT: Final = 60


@dataclass(frozen=True)
class Diagnostic:
    """A type error: the file the checker reported it in and its error code."""

    path: str
    code: str


@dataclass(frozen=True)
class ErrorFiles:
    """Files a type checker reported errors in.

    *paths* are project files relative to the project root; *outside* are
    the files with errors outside the project root, as reported.
    """

    paths: Collection[str]
    outside: Collection[str] = frozenset()


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
    executables: ClassVar[Iterable[str]] = frozenset()
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
        self._command = CommandLine(test_command)

    def version(self, root: Path) -> str | None:
        """The checker's version (``1.15.0``), or None if it cannot be found.

        Runs ``checker-version-command`` if configured, otherwise the
        ``test-command`` up to the checker's executable plus ``--version``
        (``uv run mypy --version``).
        """
        command = self.version_command or self._command.version_command(self.executables)
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

    def is_false_kill(self, stdout: str, stderr: str) -> bool:  # pragma: no mutate (truth-tested)
        """Whether a failed run reports errors, all of them from broken mutated code."""
        return self._only_false_kills(
            {diagnostic.code for diagnostic in self.diagnostics(stdout, stderr)}
        )

    def diagnostics(self, stdout: str, stderr: str) -> Iterable[Diagnostic]:
        """Errors in the output of a run, from both streams."""
        return [*self.parse_output(stdout), *self.parse_output(stderr)]

    def parse_output(self, output: str) -> Iterable[Diagnostic]:
        """Errors in one output stream; the base class knows no format."""
        return []

    def error_files(self, stdout: str, stderr: str, root: Path) -> ErrorFiles:
        """Files with errors in the output of a run in *root*."""
        project = root.resolve()
        paths: set[str] = set()
        outside: set[str] = set()
        for diagnostic in self.diagnostics(stdout, stderr):
            path = self._project_path(diagnostic.path, project)
            if path is None:
                outside.add(diagnostic.path)
            else:
                paths.add(path)
        return ErrorFiles(frozenset(paths), frozenset(outside))

    def result_dependencies(self, stdout: str, stderr: str, root: Path) -> Iterable[str] | None:
        """Project files the errors of a failed run in *root* depend on.

        The files with errors and the project files they import; None when
        that is unknown: no errors in project files, errors outside *root*,
        or a checker that cannot tell dependencies.
        """
        files = self.error_files(stdout, stderr, root)
        if len(files.outside) or not len(files.paths):
            return None
        return self.dependencies(files.paths, root)

    def config_files(self, root: Path) -> Iterable[Path]:
        """Existing checker config files in *root* that can change its results."""
        return []

    def cache_paths(self, root: Path) -> Iterable[Path]:
        """Checker cache directories inside *root* worth giving to workers."""
        return []

    def dependencies(self, files: Iterable[str], root: Path) -> Iterable[str] | None:
        """*files* and the project files they import, relative to *root*.

        None means the checker cannot tell, so no result may be reused.
        """
        return frozenset(self._graph.closure(files, root))

    def _only_false_kills(self, codes: AbstractSet[str]) -> bool:
        """Whether there are *codes* and all of them are false-kill codes."""
        return bool(codes) and codes <= self.false_kill_codes

    def _project_path(self, path: str, project: Path) -> str | None:
        """*path* relative to the resolved *project* root, or None if outside it."""
        file = Path(path)
        if not file.is_absolute():
            file = project / file
        file = file.resolve()
        if not file.is_relative_to(project):
            return None
        return file.relative_to(project).as_posix()
