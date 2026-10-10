"""Stub implementations of typemut's seams, used instead of patching code."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from parso.python.tree import BaseNode, Leaf

from typemut.checkers.base import TypeChecker
from typemut.checkers.mypy import MypyChecker
from typemut.db import MutantRow, MutantStatus
from typemut.discovery import AnnotationContext, AnnotationNode
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.parallel import GitWorkspace
from typemut.plugins.base import Plugin
from typemut.registry import Registry
from typemut.runner import CommandResult, CommandRunner, Outcome
from typemut.signals import TerminateSignal


class StubRunner:
    """CommandRunner that returns *result* for every command and records the calls."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[tuple[str, float | None, Path | None]] = []

    def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.calls.append((command, timeout, cwd))
        return self.result


class ScriptedRunner:
    """CommandRunner that answers each command with the result scripted for it.

    A command gets the result of the longest key of *results* it starts
    with, or *default*. Calls are recorded like :class:`StubRunner` does.
    """

    def __init__(
        self,
        results: Mapping[str, CommandResult],
        default: CommandResult = CommandResult(Outcome.FAILED),
    ) -> None:
        self._results = results
        self._default = default
        self.calls: list[tuple[str, float | None, Path | None]] = []

    def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.calls.append((command, timeout, cwd))
        prefixes = [prefix for prefix in self._results if command.startswith(prefix)]
        return self._results[max(prefixes, key=len)] if prefixes else self._default


class StubChecker(TypeChecker):
    """Type checker plugin run by the ``stubcheck`` command; it finds no errors."""

    name = "stub"
    executables = frozenset({"stubcheck"})


class StrictMypyChecker(MypyChecker):
    """A third-party extension of the mypy checker, run by the same ``mypy`` executable."""

    name = "mypy-strict"


class StepClock:
    """Clock whose time advances by *step* seconds each time it is read, from 0."""

    def __init__(self, step: float = 1.0) -> None:
        self._step = step
        self._now = -step

    def __call__(self) -> float:
        self._now += self._step
        return self._now


class RecordingTerminateSignal(TerminateSignal):
    """TerminateSignal that installs no handler, only counts the blocks it guards."""

    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    @contextmanager
    def interrupts(self) -> Iterator[None]:
        self.entered += 1
        try:
            yield
        finally:
            self.exited += 1


class RecordingProgressBar:
    """ProgressBar that remembers the totals it was given."""

    def __init__(self) -> None:
        self.totals: list[int] = []

    def track(self, results: Iterable[MutantRow], total: int) -> Iterable[MutantRow]:
        self.totals.append(total)
        return results


class StubExecutor:
    """MutantExecutor that gives every mutant the same *status*."""

    def __init__(self, status: MutantStatus) -> None:
        self.status = status

    def execute(self, mutants: Collection[MutantRow]) -> Iterator[MutantRow]:
        for mutant in mutants:
            yield replace(mutant, status=self.status, output="", duration_seconds=0.0)


def make_mutant(
    mutant_id: int | None = 1,
    module_path: str = "test.py",
    *,
    line: int = 1,
    col: int = 3,
    original: str = "int",
    mutated: str = "str",
) -> MutantRow:
    return MutantRow(
        id=mutant_id,
        module_path=module_path,
        operator="Test",
        line=line,
        col=col,
        original_annotation=original,
        mutated_annotation=mutated,
        description="test",
    )


class StubPlugin(Plugin):
    """Plugin that claims no annotation and adds one operator."""

    name = "stub"

    def operators(self) -> list[TypeMutationOperator]:
        return [StubOperator()]

    def find_mutations(
        self,
        annotation: AnnotationNode,
        operators: Collection[TypeMutationOperator],
        registry: Registry,
    ) -> list[Mutation] | None:
        return None


class StubOperator(TypeMutationOperator):
    """Operator outside ``[typemut.operators]`` that finds nothing."""

    name = "Stub"
    config_key = "stub"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        return []


class StubSourceReader:
    """SourceReader serving module sources from memory."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self._sources = sources

    def read(self, module_path: str) -> str | None:
        return self._sources.get(module_path)


class InterruptedCopyWorkspace(GitWorkspace):
    """GitWorkspace interrupted (as by Ctrl-C) while carrying a directory into a new worktree."""

    def __init__(self, root: Path, runner: CommandRunner, carry: Iterable[Path] = ()) -> None:
        super().__init__(root, runner, carry)
        self.interrupted: list[Path] = []

    def _copy_into(self, path: Path, worktree: Path) -> None:
        self.interrupted.append(worktree)
        raise KeyboardInterrupt
