"""Stub implementations of typemut's seams, used instead of patching code."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path

from parso.python.tree import BaseNode, Leaf

from typemut.db import MutantRow
from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.plugins.base import Plugin
from typemut.registry import Registry
from typemut.runner import CommandResult


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


class RecordingProgressBar:
    """ProgressBar that remembers the totals it was given."""

    def __init__(self) -> None:
        self.totals: list[int] = []

    def track(self, results: Iterable[MutantRow], total: int) -> Iterable[MutantRow]:
        self.totals.append(total)
        return results


class StubExecutor:
    """MutantExecutor that gives every mutant the same *status*."""

    def __init__(self, status: str) -> None:
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
