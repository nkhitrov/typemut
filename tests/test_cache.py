"""Tests for the result cache of incremental runs."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from importlib import metadata
from pathlib import Path

import pytest

from tests.fakes import ScriptedRunner, make_mutant
from typemut.cache import (
    CACHE_FORMAT_VERSION,
    UNKNOWN,
    CacheInputs,
    FileHasher,
    KillDependencies,
    ResultCache,
    Reuse,
    TypemutVersion,
)
from typemut.checkers.generic import GenericChecker
from typemut.checkers.mypy import MypyChecker
from typemut.config import Config
from typemut.db import Database, MutantRow
from typemut.runner import CommandResult, Outcome


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """``test.py`` imports ``dep.py``; ``other.py`` is unrelated."""
    (tmp_path / "test.py").write_text("import dep\nx: int = 1\n")
    (tmp_path / "dep.py").write_text("y = 1\n")
    (tmp_path / "other.py").write_text("z = 1\n")
    return tmp_path


# --- hashing ---


def test_file_hasher_digests(project: Path) -> None:
    assert FileHasher().digests(project, ["dep.py", "missing.py", "dep.py"]) == {
        "dep.py": _sha("y = 1\n"),
        "missing.py": "",
    }


def test_typemut_version_hashes_sources(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("a = 1\n")
    (tmp_path / "sub" / "b.py").write_text("b = 1\n")
    (tmp_path / "notes.txt").write_text("not a source\n")
    before = TypemutVersion(tmp_path).fingerprint()
    (tmp_path / "notes.txt").write_text("changed\n")
    unchanged = TypemutVersion(tmp_path).fingerprint()
    (tmp_path / "sub" / "b.py").write_text("b = 2\n")
    after = TypemutVersion(tmp_path).fingerprint()
    assert before.startswith(metadata.version("typemut") + "+")
    assert before == unchanged
    assert before != after


def test_typemut_version_of_installed_package() -> None:
    assert TypemutVersion().fingerprint().startswith(metadata.version("typemut") + "+")


# --- cache inputs ---


def _mypy(runner: ScriptedRunner | None = None) -> MypyChecker:
    return MypyChecker(
        "uv run mypy src",
        runner=runner
        or ScriptedRunner(
            {
                "uv run mypy --version": CommandResult(Outcome.PASSED, "mypy 1.15.0\n"),
                "uv run python --version": CommandResult(Outcome.PASSED, "Python 3.12.4\n"),
            }
        ),
        environ={},
    )


def test_cache_inputs(project: Path) -> None:
    (project / "mypy.ini").write_text("[mypy]\n")
    (project / "uv.lock").write_text("lock\n")
    (project / "requirements-dev.txt").write_text("mypy\n")
    (project / "requirements.d").mkdir()
    meta = CacheInputs(project).meta(
        Config(test_command="uv run mypy src", timeout=20), _mypy(), "0.1.0+abc"
    )
    assert meta == {
        "cache format": CACHE_FORMAT_VERSION,
        "typemut version": "0.1.0+abc",
        "checker": "mypy",
        "checker version": "1.15.0",
        "checker python": "3.12.4",
        "test-command": "uv run mypy src",
        "timeout": "20",
        "checker config mypy.ini": _sha("[mypy]\n"),
        "file requirements-dev.txt": _sha("mypy\n"),
        "file uv.lock": _sha("lock\n"),
    }


def test_cache_inputs_with_unknown_versions(project: Path) -> None:
    inputs = CacheInputs(project)
    meta = inputs.meta(Config(cache_key_files=[]), _mypy(ScriptedRunner({})), "0.1.0")
    assert (meta["checker version"], meta["checker python"]) == (UNKNOWN, UNKNOWN)
    assert not inputs.knows_checker_version(meta)
    assert inputs.knows_checker_version({"checker version": "1.0"})


# --- reuse ---


def _cache(project: Path) -> tuple[Database, ResultCache]:
    db = Database(project / "typemut.sqlite")
    return db, ResultCache(db, project)


def _result(status: str, depends: dict[str, str] | None, line: int = 2) -> MutantRow:
    """A finished mutant of ``test.py``."""
    mutant = make_mutant(None, "test.py", line=line)
    return replace(mutant, status=status, output=f"{status} output", depends=depends)


def test_validate(project: Path) -> None:
    db, cache = _cache(project)
    with db:
        first = cache.validate({"checker": "mypy", "timeout": "30"})
        cache.save([_result("killed", {})])
        same = cache.validate({"checker": "mypy", "timeout": "30"})
        kept = len(db.cache.load())
        changed = cache.validate({"checker": "mypy", "file uv.lock": "x"})
        dropped = db.cache.load()
    assert (first, same, kept) == ("no earlier results", None, 1)
    assert changed == "file uv.lock, timeout changed"
    assert dropped == {}


def test_save_skips_pending(project: Path) -> None:
    db, cache = _cache(project)
    with db:
        cache.save([_result("pending", None), _result("survived", None, line=3)])
        cached = db.cache.load()
    assert [mutant.status for mutant in cached.values()] == ["survived"]


def test_carry_over_keeps_only_traced_kills(project: Path) -> None:
    db, cache = _cache(project)
    traced = _result("killed", {"test.py": "1"}, line=1)
    with db:
        cache.save([traced, _result("killed", {"dep.py": "2"}, line=2)])
        cache.carry_over(
            [
                replace(traced, depends=None, output="untracked run"),
                _result("killed", None, line=2),
                _result("survived", None, line=3),
                _result("killed", {"other.py": "3"}, line=4),
            ]
        )
        cached = db.cache.load()
    assert [(m.line, m.output, m.depends) for m in cached.values()] == [
        (1, "killed output", {"test.py": "1"}),
        (2, "killed output", {"dep.py": "2"}),
        (4, "killed output", {"other.py": "3"}),
    ]


def test_reuse(project: Path) -> None:
    unchanged = {"test.py": _sha("import dep\nx: int = 1\n"), "dep.py": _sha("y = 1\n")}
    db, cache = _cache(project)
    with db:
        cache.save(
            [
                _result("killed", unchanged, line=1),
                _result("killed", {**unchanged, "dep.py": _sha("y = 2\n")}, line=2),
                _result("killed", {"gone.py": _sha("")}, line=3),
                _result("killed", None, line=4),
                _result("survived", unchanged, line=5),
                _result("error", unchanged, line=6),
            ]
        )
        pending = [make_mutant(index, "test.py", line=index) for index in range(1, 8)]
        found = cache.reuse(pending)
    assert found == Reuse(
        [
            replace(
                pending[0],
                status="killed",
                output="killed output",
                duration_seconds=0.0,
                depends=unchanged,
            )
        ],
        stale=2,
        untraceable=1,
    )


def test_reuse_from_empty_cache(project: Path) -> None:
    db, cache = _cache(project)
    with db:
        assert cache.reuse([make_mutant()]) == Reuse([])


# --- kill dependencies ---


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(
            CommandResult(Outcome.FAILED, "test.py:2: error: x  [assignment]\n"),
            {"test.py": _sha("import dep\nx: int = 1\n"), "dep.py": _sha("y = 1\n")},
            id="error-in-mutated-file",
        ),
        pytest.param(
            CommandResult(Outcome.FAILED, "other.py:1: error: x  [assignment]\n"),
            {"test.py": _sha("import dep\nx: int = 1\n"), "other.py": _sha("z = 1\n")},
            id="error-in-other-file",
        ),
        pytest.param(
            CommandResult(Outcome.FAILED, "Found 1 error\n"), None, id="no-error-files"
        ),
        pytest.param(CommandResult(Outcome.TIMED_OUT), None, id="timeout"),
        pytest.param(
            CommandResult(Outcome.PASSED, "test.py:2: error: x  [assignment]\n"),
            None,
            id="passed",
        ),
    ],
)
def test_kill_dependencies(
    result: CommandResult, expected: dict[str, str] | None, project: Path
) -> None:
    mutant = make_mutant(module_path="test.py")
    assert KillDependencies(MypyChecker()).depends(mutant, result, project) == expected


def test_no_kill_dependencies_from_generic_checker(project: Path) -> None:
    result = CommandResult(Outcome.FAILED, "test.py:2: error: x  [assignment]\n")
    assert KillDependencies(GenericChecker()).depends(make_mutant(), result, project) is None
