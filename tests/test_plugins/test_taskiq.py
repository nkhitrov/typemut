"""Tests for the taskiq plugin."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from typemut.cli import main
from typemut.db import Database
from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry

IMPORTS = "from typing import Annotated\nfrom taskiq import InMemoryBroker, TaskiqDepends\n"

# The annotation under test: RemoveOptional mutates it wherever it is not skipped.
TARGET = "Out | None"


def mutated(root: Path, files: dict[str, str], module: str) -> set[str]:
    """Originals of the mutations in *module*, with the plugin scanning all *files*."""
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    plugins = PluginRegistry().get(["taskiq"])
    project = sorted(root.rglob("*.py"))
    for plugin in plugins:
        plugin.scan(project)
    finder = MutationFinder(OperatorRegistry().enabled({}), Registry(), plugins)
    return {
        mutation.original
        for annotation in AnnotationFinder().find(root / module)
        for mutation in finder.find(annotation)
    }


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="annotated-provider-return",
        ),
        pytest.param(
            f"async def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(dep, use_cache=False)]) -> None: ...\n",
            id="async-provider-with-options",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(use_cache=False, dependency=dep)]) -> None: ...\n",
            id="dependency-keyword",
        ),
        pytest.param(
            f"def common() -> {TARGET}: ...\n"
            "def dep(c: Annotated[int, TaskiqDepends(common)]) -> None: ...\n",
            id="referenced-by-another-provider",
        ),
        pytest.param(
            "class Checker:\n"
            f"    def __call__(self) -> {TARGET}: ...\n"
            "checker = Checker()\n"
            "def task(d: Annotated[int, TaskiqDepends(checker)]) -> None: ...\n",
            id="callable-instance",
        ),
        pytest.param(
            f"def task(context: {TARGET} = TaskiqDepends()) -> None: ...\n",
            id="hint-dependency-parameter",
        ),
        pytest.param(
            f"def task(context: Annotated[{TARGET}, TaskiqDepends()]) -> None: ...\n",
            id="annotated-hint-dependency-parameter",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "class Tasks:\n"
            "    def run(self, d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="referenced-from-method",
        ),
    ],
)
def test_injected_signature_is_skipped(tmp_path: Path, source: str) -> None:
    assert mutated(tmp_path, {"main.py": IMPORTS + source}, "main.py") == set()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(f"def dep() -> {TARGET}: ...\n", id="unreferenced-function"),
        pytest.param(
            f"def dep(x: {TARGET} = TaskiqDepends(other)) -> None: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="provider-parameter",
        ),
        pytest.param(
            "class DAO:\n"
            f"    def __init__(self, conn: {TARGET} = TaskiqDepends(other)) -> None: ...\n"
            "def task(d: Annotated[DAO, TaskiqDepends()]) -> None: ...\n",
            id="class-provider-parameter",
        ),
        pytest.param(
            "class Outer:\n"
            "    class Checker:\n"
            f"        def __call__(self) -> {TARGET}: ...\n"
            "checker = Outer.Checker()\n"
            "def task(d: Annotated[int, TaskiqDepends(checker)]) -> None: ...\n",
            id="nested-class-provider",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\ndef task(d: int = TaskiqDepends(dep)) -> None: ...\n",
            id="return-checked-through-default",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n"
            "def other(d: int = TaskiqDepends(dep)) -> None: ...\n",
            id="return-checked-through-one-default",
        ),
        pytest.param(
            "def dep() -> None: ...\n"
            f"def task(x: {TARGET}, d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="task-parameter",
        ),
        pytest.param(
            f"def dep() -> None: ...\ndef task(d: {TARGET} = TaskiqDepends(dep)) -> None: ...\n",
            id="explicit-provider-parameter",
        ),
        pytest.param(
            "def dep() -> None:\n"
            f"    x: {TARGET} = None\n"
            "def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="provider-body",
        ),
        pytest.param(
            "class DAO:\n"
            f"    def get(self) -> {TARGET}: ...\n"
            "def task(d: Annotated[DAO, TaskiqDepends(DAO)]) -> None: ...\n",
            id="other-method-of-class-provider",
        ),
        pytest.param(
            "from fastapi import Depends\n"
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, Depends(dep)]) -> None: ...\n",
            id="other-depends",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\ndef task(d: int = make(dep)) -> None: ...\n",
            id="other-call",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(make(dep))]) -> None: ...\n",
            id="provider-built-by-call",
        ),
        pytest.param(
            "def outer() -> None:\n"
            f"    def dep() -> {TARGET}: ...\n"
            "    def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="nested-provider",
        ),
        pytest.param(
            f"def dep() -> {TARGET}: ...\n"
            "def task(d: Annotated[int, TaskiqDepends(lambda: dep)]) -> None: ...\n",
            id="lambda-provider",
        ),
        pytest.param(
            "from taskiq import TaskiqEvents, TaskiqState\n"
            "broker = InMemoryBroker()\n"
            "@broker.on_event(TaskiqEvents.WORKER_STARTUP)\n"
            f"async def startup(state: TaskiqState) -> {TARGET}: ...\n",
            id="event-handler",
        ),
    ],
)
def test_checked_signature_is_mutated(tmp_path: Path, source: str) -> None:
    assert mutated(tmp_path, {"main.py": IMPORTS + source}, "main.py") == {TARGET}


@pytest.mark.parametrize(
    "tasks",
    [
        pytest.param(
            "from typing import Annotated\nfrom taskiq import TaskiqDepends\n"
            "from .deps import dep\n"
            "def task(d: Annotated[int, TaskiqDepends(dep)]) -> None: ...\n",
            id="relative-import",
        ),
        pytest.param(
            "import taskiq\nfrom pkg import deps\n"
            "def task(d: Annotated[int, taskiq.TaskiqDepends(deps.dep)]) -> None: ...\n",
            id="module-attributes",
        ),
        pytest.param(
            "import pkg.deps as d\nfrom taskiq_dependencies import Depends\n"
            "def task(x: Annotated[int, Depends(d.dep)]) -> None: ...\n",
            id="taskiq-dependencies-depends",
        ),
        pytest.param(
            "from pkg.deps import dep\nfrom taskiq_dependencies.dependency import Depends as D\n"
            "def task(x: Annotated[int, D(dep)]) -> None: ...\n",
            id="aliased-depends",
        ),
    ],
)
def test_provider_in_another_module(tmp_path: Path, tasks: str) -> None:
    files = {
        "pkg/__init__.py": "",
        "pkg/deps.py": f"def dep() -> {TARGET}: ...\n",
        "pkg/tasks.py": tasks,
    }
    assert mutated(tmp_path, files, "pkg/deps.py") == set()


def test_init_scans_project_files(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        root = Path(td)
        (root / "typemut.toml").write_text(
            '[typemut]\nmodule-path = "src"\ntest-command = "true"\nplugins = ["taskiq"]\n'
        )
        (root / "src").mkdir()
        (root / "src" / "deps.py").write_text(f"def dep() -> {TARGET}: ...\n")
        (root / "src" / "tasks.py").write_text(
            f"{IMPORTS}from deps import dep\n"
            f"def task(d: Annotated[int, TaskiqDepends(dep)]) -> {TARGET}: ...\n"
        )
        result = runner.invoke(main, ["init"])
        with Database(root / "typemut.sqlite") as db:
            modules = {Path(mutant.module_path).name for mutant in db.get_all()}
    assert result.exit_code == 0
    assert modules == {"tasks.py"}
