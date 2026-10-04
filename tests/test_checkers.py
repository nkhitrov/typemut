"""Tests for the type checker plugins and their registry."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from tests.fakes import ScriptedRunner, StubChecker
from typemut.checkers import AUTO, BUILTIN_CHECKERS, ENTRY_POINT_GROUP, CheckerRegistry
from typemut.checkers.base import VERSION_TIMEOUT, Diagnostic, ErrorFiles, TypeChecker
from typemut.checkers.generic import GenericChecker
from typemut.checkers.graph import ImportGraph
from typemut.checkers.mypy import NO_CODE, MypyChecker
from typemut.checkers.pyright import NO_RULE, BasedPyrightChecker, PyrightChecker
from typemut.engine import OutcomeClassifier
from typemut.runner import CommandResult, Outcome

# Real output of ``mypy a.py`` and of the same run with ``--pretty``.
MYPY_OUTPUT = """\
a.py:3: error: Incompatible return value type (got "int", expected "str")  [return-value]
a.py:4: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]
a.py:5: error: Name "Foo" is not defined  [name-defined]
a.py:7: error: "int" has no attribute "upper"  [attr-defined]
Found 4 errors in 1 file (checked 1 source file)
"""
MYPY_PRETTY_OUTPUT = """\
a.py:3: error: Incompatible return value type (got "int", expected "str")
[return-value]
        return x
               ^
a.py:4: error: Incompatible types in assignment (expression has type "str",
variable has type "int")  [assignment]
    y: int = "a very long string literal that should make the message wrap...
             ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~...
a.py:5: error: Name "Foo" is not defined  [name-defined]
    z: Foo = 1
       ^
a.py:7: error: "int" has no attribute "upper"  [attr-defined]
        return items[key].upper()  [not-a-code]
               ^~~~~~~~~~~~~~~~
Found 4 errors in 1 file (checked 1 source file)
"""
# ``--show-column-numbers --show-error-end``
MYPY_COLUMNS_OUTPUT = """\
a.py:3:12:3:12: error: Incompatible return value type (got "int", expected "str")  [return-value]
a.py:5:4:5:4: error: Name "Foo" is not defined  [name-defined]
Found 2 errors in 1 file (checked 1 source file)
"""
MYPY_DIAGNOSTICS = [
    Diagnostic("a.py", "return-value"),
    Diagnostic("a.py", "assignment"),
    Diagnostic("a.py", "name-defined"),
    Diagnostic("a.py", "attr-defined"),
]

PROJECT = "/proj"


def pyright_output(root: str = PROJECT) -> str:
    """Real pyright output (``pyright a.py b.py``) for a project in *root*."""
    return f"""\
{root}/a.py
  {root}/a.py:3:12 - error: Type "int" is not assignable to return type "str"
    "int" is not assignable to "str" (reportReturnType)
  {root}/a.py:5:4 - error: "Foo" is not defined (reportUndefinedVariable)
  {root}/a.py:6:15 - warning: Unnecessary "# type: ignore" comment (reportUnnecessaryTypeIgnoreComment)
  {root}/a.py:7:13 - information: Type of "x" is "Literal[1]"
{root}/b.py
  {root}/b.py:1:8 - error: Import "nothere" could not be resolved (reportMissingImports)
  {root}/b.py:3:5 - error: Expected expression
4 errors, 1 warning, 1 information
"""


PYRIGHT_DIAGNOSTICS = [
    Diagnostic(f"{PROJECT}/a.py", "reportReturnType"),
    Diagnostic(f"{PROJECT}/a.py", "reportUndefinedVariable"),
    Diagnostic(f"{PROJECT}/b.py", "reportMissingImports"),
    Diagnostic(f"{PROJECT}/b.py", NO_RULE),
]


def _passing(stdout: str = "", stderr: str = "") -> ScriptedRunner:
    """A runner on which every command passes with this output."""
    return ScriptedRunner({"": CommandResult(Outcome.PASSED, stdout, stderr)})


# --- version ---


@pytest.mark.parametrize(
    ("checker", "test_command", "version_command"),
    [
        pytest.param(MypyChecker, "mypy src/", "mypy --version", id="plain"),
        pytest.param(MypyChecker, "uv run mypy src/", "uv run mypy --version", id="uv"),
        pytest.param(PyrightChecker, "poetry run pyright", "poetry run pyright --version", id="poetry"),
        pytest.param(MypyChecker, "python -m mypy -p app", "python -m mypy --version", id="module"),
        pytest.param(MypyChecker, ".venv/bin/mypy .", ".venv/bin/mypy --version", id="path"),
        pytest.param(MypyChecker, "cd src && mypy .", "mypy --version", id="chained"),
        pytest.param(MypyChecker, "dmypy run -- src", "dmypy --version", id="dmypy"),
        pytest.param(BasedPyrightChecker, "basedpyright src", "basedpyright --version", id="based"),
    ],
)
def test_version_command_from_test_command(
    checker: type[TypeChecker], test_command: str, version_command: str, tmp_path: Path
) -> None:
    runner = _passing("mypy 1.19.1 (compiled: yes)\n")
    assert checker(test_command, runner=runner).version(tmp_path) == "1.19.1"
    assert runner.calls == [(version_command, VERSION_TIMEOUT, tmp_path)]


def test_version_command_override(tmp_path: Path) -> None:
    runner = _passing("pyright 1.1.414\n")
    checker = PyrightChecker("make typecheck", "npx pyright --version", runner)
    assert checker.version(tmp_path) == "1.1.414"
    assert runner.calls == [("npx pyright --version", VERSION_TIMEOUT, tmp_path)]


@pytest.mark.parametrize(
    ("stdout", "stderr", "version"),
    [
        pytest.param("mypy 1.20.0+dev.abc123 (compiled: no)\n", "", "1.20.0+dev.abc123", id="dev"),
        pytest.param("", "pyright 1.1.414\n", "1.1.414", id="stderr"),
        pytest.param("mypy 1.19.1\n", "uv 0.9.2 resolved\n", "1.19.1", id="stdout-first"),
    ],
)
def test_version_from_output(stdout: str, stderr: str, version: str, tmp_path: Path) -> None:
    assert MypyChecker("mypy .", runner=_passing(stdout, stderr)).version(tmp_path) == version


@pytest.mark.parametrize(
    "test_command",
    [
        pytest.param("make typecheck", id="no-executable"),
        pytest.param("mypy 'src", id="unbalanced-quote"),
    ],
)
def test_no_version_without_command(test_command: str, tmp_path: Path) -> None:
    runner = _passing("mypy 1.19.1\n")
    assert MypyChecker(test_command, runner=runner).version(tmp_path) is None
    assert runner.calls == []


def test_no_version_when_command_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    runner = ScriptedRunner({}, CommandResult(Outcome.FAILED, stderr="mypy: not found\n"))
    assert MypyChecker("mypy .", runner=runner).version(tmp_path) is None
    assert "Version command 'mypy --version' failed: mypy: not found" in caplog.text


def test_no_version_in_output(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert MypyChecker("mypy .", runner=_passing("mypy dev\n")).version(tmp_path) is None
    assert "No version number in the output of 'mypy --version'" in caplog.text


def test_generic_version_only_from_version_command(tmp_path: Path) -> None:
    runner = _passing("tool 2.0.1\n")
    assert GenericChecker("make typecheck", runner=runner).version(tmp_path) is None
    assert GenericChecker("make typecheck", "tool -V", runner).version(tmp_path) == "2.0.1"


# --- mypy output ---


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param(MYPY_OUTPUT, MYPY_DIAGNOSTICS, id="default"),
        pytest.param(MYPY_PRETTY_OUTPUT, MYPY_DIAGNOSTICS, id="pretty"),
        pytest.param(
            MYPY_COLUMNS_OUTPUT,
            [Diagnostic("a.py", "return-value"), Diagnostic("a.py", "name-defined")],
            id="columns",
        ),
        pytest.param(
            'a.py:2: note: Revealed type is "builtins.int"\n'
            "a.py:3: note: See https://mypy.rtfd.io  [misc]\n",
            [],
            id="notes",
        ),
        pytest.param(
            'a.py:1: error: Name "x" is not defined\nFound 1 error in 1 file\n',
            [Diagnostic("a.py", NO_CODE)],
            id="hidden-codes",
        ),
        pytest.param(
            "a.py:1: error: Invalid syntax\nb.pyi:2: error: x  [misc]\n",
            [Diagnostic("a.py", NO_CODE), Diagnostic("b.pyi", "misc")],
            id="no-code-then-error",
        ),
        pytest.param(
            "a.py:1: error: Unsupported operand\n    x + 1\n",
            [Diagnostic("a.py", NO_CODE)],
            id="no-code-pretty",
        ),
        pytest.param("a.py:1: error: Bad", [Diagnostic("a.py", NO_CODE)], id="no-code-last"),
        pytest.param("Success: no issues found in 1 source file\n", [], id="success"),
    ],
)
def test_mypy_diagnostics(output: str, expected: list[Diagnostic]) -> None:
    assert MypyChecker().diagnostics(output, "") == expected


def test_mypy_diagnostics_from_both_streams() -> None:
    stderr = "warning: `VIRTUAL_ENV=.venv` does not match the project environment\n"
    diagnostics = MypyChecker().diagnostics("a.py:1: error: x  [syntax]\n", stderr)
    assert diagnostics == [Diagnostic("a.py", "syntax")]
    assert MypyChecker().diagnostics("", "a.py:1: error: x  [misc]\n") == [Diagnostic("a.py", "misc")]


@pytest.mark.parametrize(
    ("output", "false_kill"),
    [
        pytest.param('a.py:5: error: Name "Foo" is not defined  [name-defined]\n', True, id="name"),
        pytest.param(
            "a.py:5: error: invalid syntax  [syntax]\na.py:6: error: x  [valid-type]\n",
            True,
            id="only-false-kill-codes",
        ),
        pytest.param(MYPY_OUTPUT, False, id="real-kill"),
        pytest.param('a.py:5: error: Name "Foo" is not defined\n', False, id="no-code"),
        pytest.param("", False, id="no-errors"),
    ],
)
def test_mypy_false_kill(output: str, false_kill: bool) -> None:
    assert MypyChecker().is_false_kill(output, "") is false_kill


# --- pyright output ---


def test_pyright_diagnostics() -> None:
    assert PyrightChecker().diagnostics(pyright_output(), "") == PYRIGHT_DIAGNOSTICS


def test_basedpyright_diagnostics() -> None:
    assert BasedPyrightChecker().diagnostics("", pyright_output()) == PYRIGHT_DIAGNOSTICS


def test_pyright_rule_on_last_line_of_message() -> None:
    output = (
        "  /proj/a.py:1:1 - error: First (reportCallIssue) line\n"
        "    continues (reportArgumentType)\n"
        "  /proj/a.py:2:1 - error: Last line\n"
        "    has no rule (reportX) here\n"
    )
    assert PyrightChecker().diagnostics(output, "") == [
        Diagnostic("/proj/a.py", "reportArgumentType"),
        Diagnostic("/proj/a.py", NO_RULE),
    ]


@pytest.mark.parametrize(
    ("output", "false_kill"),
    [
        pytest.param(
            '  /proj/a.py:5:4 - error: "Foo" is not defined (reportUndefinedVariable)\n',
            True,
            id="undefined",
        ),
        pytest.param(
            "  /proj/a.py:5:4 - error: Variable not allowed in type expression"
            " (reportInvalidTypeForm)\n",
            True,
            id="type-form",
        ),
        pytest.param("  /proj/b.py:3:5 - error: Expected expression\n", True, id="syntax"),
        pytest.param(pyright_output(), False, id="real-kill"),
        pytest.param(
            "  /proj/a.py:6:15 - warning: Unused (reportUnusedImport)\n0 errors, 1 warning\n",
            False,
            id="warning-only",
        ),
    ],
)
def test_pyright_false_kill(output: str, false_kill: bool) -> None:
    assert PyrightChecker().is_false_kill(output, "") is false_kill


# --- generic ---


def test_generic_reads_codes_from_any_line() -> None:
    output = "check failed\nmodels.py(3): Name not defined  [name-defined]\n"
    assert GenericChecker().diagnostics(output, "") == [Diagnostic("", "name-defined")]
    assert GenericChecker().is_false_kill(output, "") is True


def test_generic_knows_no_files(tmp_path: Path) -> None:
    checker = GenericChecker("make typecheck")
    assert checker.error_files(MYPY_OUTPUT, "", tmp_path) == ErrorFiles(frozenset())
    assert checker.dependencies(["a.py"], tmp_path) is None
    assert (checker.config_files(tmp_path), checker.cache_paths(tmp_path)) == ([], [])


@pytest.mark.parametrize(
    ("checker", "output", "status"),
    [
        pytest.param(GenericChecker(), "x  [name-defined]\n", "error", id="generic"),
        pytest.param(MypyChecker(), MYPY_PRETTY_OUTPUT, "killed", id="mypy-kill"),
        pytest.param(
            MypyChecker(), 'a.py:1: error: Name "Foo" is not defined\n[name-defined]\n', "error",
            id="mypy-pretty-false-kill",
        ),
        pytest.param(MypyChecker(), "x  [name-defined]\n", "killed", id="mypy-needs-header"),
        pytest.param(
            PyrightChecker(), "  /p/a.py:1:1 - error: Expected expression\n", "error", id="pyright"
        ),
    ],
)
def test_classifier_uses_checker(checker: TypeChecker, output: str, status: str) -> None:
    result = CommandResult(Outcome.FAILED, stdout=output, stderr="Resolved 3 packages\n")
    assert OutcomeClassifier(checker).classify(result) == (status, result.output)


def test_base_checker_knows_no_format(tmp_path: Path) -> None:
    checker = TypeChecker("mypy .")
    assert checker.diagnostics(MYPY_OUTPUT, "") == []
    assert checker.is_false_kill(MYPY_OUTPUT, "") is False
    assert (checker.config_files(tmp_path), checker.cache_paths(tmp_path)) == ([], [])


# --- error files ---


def test_error_files_relative_to_root(tmp_path: Path) -> None:
    output = "src/a.py:1: error: x  [misc]\nsrc/pkg/b.py:2: error: y  [misc]\n"
    assert MypyChecker().error_files(output, "", tmp_path) == ErrorFiles(
        frozenset({"src/a.py", "src/pkg/b.py"})
    )


def test_error_files_through_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    files = PyrightChecker().error_files(pyright_output(str(real.resolve())), "", link)
    assert files == ErrorFiles(frozenset({"a.py", "b.py"}))


@pytest.mark.parametrize(
    "outside",
    [
        pytest.param("/usr/lib/python3.13/site-packages/pkg/mod.py", id="site-packages"),
        pytest.param("../other/mod.py", id="parent"),
    ],
)
def test_error_files_outside_root(outside: str, tmp_path: Path) -> None:
    output = f"a.py:1: error: x  [misc]\n{outside}:9: error: y  [override]\n"
    assert MypyChecker().error_files(output, "", tmp_path) == ErrorFiles(
        frozenset({"a.py"}), external=True
    )


# --- config files ---


def _touch(root: Path, *names: str) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("")


def test_mypy_config_files(tmp_path: Path) -> None:
    _touch(tmp_path, "setup.cfg", "pyproject.toml", "mypy.ini", "conf/strict.ini")
    assert MypyChecker("mypy --config-file conf/strict.ini .").config_files(tmp_path) == [
        tmp_path / "conf/strict.ini",
        tmp_path / "mypy.ini",
        tmp_path / "pyproject.toml",
        tmp_path / "setup.cfg",
    ]


def test_mypy_config_files_skip_missing(tmp_path: Path) -> None:
    _touch(tmp_path, ".mypy.ini", "mypy.ini")
    checker = MypyChecker("mypy --config-file=missing.ini --config-file mypy.ini .")
    assert checker.config_files(tmp_path) == [tmp_path / "mypy.ini", tmp_path / ".mypy.ini"]


@pytest.mark.parametrize(
    ("test_command", "files", "expected"),
    [
        pytest.param("pyright", ("pyproject.toml", "pyrightconfig.json"), ["pyrightconfig.json", "pyproject.toml"], id="default"),
        pytest.param("pyright -p ci", ("ci/pyrightconfig.json",), ["ci/pyrightconfig.json"], id="project-dir"),
        pytest.param("pyright --project=ci.json", ("ci.json",), ["ci.json"], id="project-file"),
        pytest.param("pyright --project", ("pyproject.toml",), ["pyproject.toml"], id="no-value"),
    ],
)
def test_pyright_config_files(
    test_command: str, files: tuple[str, ...], expected: list[str], tmp_path: Path
) -> None:
    _touch(tmp_path, *files)
    found = PyrightChecker(test_command).config_files(tmp_path)
    assert found == [tmp_path / name for name in expected]


# --- cache paths ---


@pytest.mark.parametrize(
    ("test_command", "environ", "configs", "cache_dir"),
    [
        pytest.param("mypy .", {}, {}, ".mypy_cache", id="default"),
        pytest.param("mypy --cache-dir build/mypy .", {"MYPY_CACHE_DIR": "env"}, {}, "build/mypy", id="flag"),
        pytest.param("mypy --cache-dir=flag .", {}, {}, "flag", id="flag-equals"),
        pytest.param("mypy .", {"MYPY_CACHE_DIR": "env"}, {"mypy.ini": "[mypy]\ncache_dir = ini\n"}, "env", id="env"),
        pytest.param(
            "mypy .",
            {},
            {"mypy.ini": "[mypy]\ncache_dir = ini\n", "pyproject.toml": '[tool.mypy]\ncache_dir = "toml"\n'},
            "ini",
            id="ini-before-pyproject",
        ),
        pytest.param(
            "mypy .",
            {},
            {"setup.cfg": "[flake8]\nx = 1\n", "pyproject.toml": '[tool.mypy]\ncache_dir = "toml"\n'},
            "toml",
            id="pyproject",
        ),
        pytest.param(
            "mypy .", {}, {"setup.cfg": "[mypy]\ncache_dir = cfg\n"}, "cfg", id="setup-cfg"
        ),
        pytest.param(
            "mypy --config-file ci.toml .",
            {},
            {"ci.toml": '[tool.mypy]\ncache_dir = "ci"\n', "mypy.ini": "[mypy]\ncache_dir = ini\n"},
            "ci",
            id="config-file",
        ),
        pytest.param(
            "mypy .", {}, {"mypy.ini": "[mypy]\nstrict = True\n", "setup.cfg": "[mypy]\ncache_dir = cfg\n"},
            ".mypy_cache", id="first-config-without-cache-dir",
        ),
        pytest.param(
            "mypy .", {}, {"pyproject.toml": "[tool.mypy]\ncache_dir = 1\n"}, ".mypy_cache", id="not-a-string"
        ),
        pytest.param(
            "mypy .",
            {},
            {"pyproject.toml": "[tool.mypy\n", "setup.cfg": "[mypy]\ncache_dir = cfg\n"},
            "cfg",
            id="broken-toml",
        ),
        pytest.param(
            "mypy .",
            {},
            {"mypy.ini": "cache_dir = nosection\n", "setup.cfg": "[mypy]\ncache_dir = cfg\n"},
            "cfg",
            id="broken-ini",
        ),
        pytest.param(
            "mypy .", {}, {"pyproject.toml": "[tool]\nmypy = 1\n"}, ".mypy_cache", id="not-a-table"
        ),
    ],
)
def test_mypy_cache_paths(
    test_command: str,
    environ: dict[str, str],
    configs: dict[str, str],
    cache_dir: str,
    tmp_path: Path,
) -> None:
    for name, text in configs.items():
        (tmp_path / name).write_text(text)
    checker = MypyChecker(test_command, environ=environ)
    assert checker.cache_paths(tmp_path) == [tmp_path / cache_dir]


@pytest.mark.parametrize(
    "cache_dir",
    [
        pytest.param("/tmp/typemut-elsewhere", id="absolute"),
        pytest.param("../cache", id="parent"),
    ],
)
def test_mypy_cache_outside_root_is_not_used(
    cache_dir: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    checker = MypyChecker(f"mypy --cache-dir {cache_dir} .", environ={})
    assert checker.cache_paths(tmp_path) == []
    assert "is outside the project" in caplog.text


def test_mypy_cache_from_process_environment(tmp_path: Path) -> None:
    assert MypyChecker("mypy --cache-dir c .").cache_paths(tmp_path) == [tmp_path / "c"]


def test_pyright_has_no_cache(tmp_path: Path) -> None:
    assert PyrightChecker("pyright").cache_paths(tmp_path) == []


# --- dependencies ---


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        {
            "src/app/__init__.py": "",
            "src/app/models.py": "import os\nfrom app.base import Base\n\nclass User(Base): ...\n",
            "src/app/base.py": "from . import types\nfrom .util import *\n",
            "src/app/types.py": "import app.base as base\n",
            "src/app/util.py": "",
            "src/app/api.py": "from app import models\n",
            "src/app/unrelated.py": "import json\n",
        },
    )
    return tmp_path


def test_dependencies_follow_project_imports(project: Path) -> None:
    assert MypyChecker().dependencies(["src/app/models.py"], project) == {
        "src/app/__init__.py",
        "src/app/base.py",
        "src/app/models.py",
        "src/app/types.py",
        "src/app/util.py",
    }


def test_dependencies_of_several_files(project: Path) -> None:
    deps = PyrightChecker().dependencies(["src/app/api.py", "src/app/unrelated.py"], project)
    assert deps == {
        "src/app/__init__.py",
        "src/app/api.py",
        "src/app/base.py",
        "src/app/models.py",
        "src/app/types.py",
        "src/app/unrelated.py",
        "src/app/util.py",
    }


def test_dependencies_keep_unreadable_files(tmp_path: Path) -> None:
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe import x\n")
    deps = ImportGraph().closure(["binary.py", "missing.py"], tmp_path)
    assert deps == {"binary.py", "missing.py"}


def test_dependencies_through_symlinked_root(project: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    link = tmp_path_factory.mktemp("links") / "project"
    link.symlink_to(project)
    assert ImportGraph().closure(["src/app/api.py"], link) >= {"src/app/models.py"}


# --- registry ---


@pytest.mark.parametrize(
    ("test_command", "checker"),
    [
        pytest.param("mypy src/", MypyChecker, id="mypy"),
        pytest.param("uv run dmypy run -- src", MypyChecker, id="dmypy"),
        pytest.param("poetry run pyright", PyrightChecker, id="pyright"),
        pytest.param("basedpyright src", BasedPyrightChecker, id="basedpyright"),
        pytest.param("mypy src && pyright src", PyrightChecker, id="pyright-first"),
    ],
)
def test_detect_checker(test_command: str, checker: type[TypeChecker]) -> None:
    assert type(CheckerRegistry().get(None, test_command)) is checker
    assert type(CheckerRegistry().get(AUTO, test_command)) is checker


def test_detect_unknown_command_falls_back_to_generic(caplog: pytest.LogCaptureFixture) -> None:
    assert type(CheckerRegistry().get(None, "make typecheck")) is GenericChecker
    assert "Could not detect the type checker in test-command 'make typecheck'" in caplog.text


def test_get_checker_by_name() -> None:
    runner = _passing()
    checker = CheckerRegistry().get("mypy", "make typecheck", "mypy --version", runner)
    assert type(checker) is MypyChecker
    assert (checker.test_command, checker.version_command) == ("make typecheck", "mypy --version")


def test_unknown_checker_name_falls_back_to_generic(caplog: pytest.LogCaptureFixture) -> None:
    assert type(CheckerRegistry().get("pytype", "mypy src")) is GenericChecker
    assert (
        "Unknown checker 'pytype', using 'generic'. "
        "Available checkers: basedpyright, generic, mypy, pyright" in caplog.text
    )


def _entry_point(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def test_discover_adds_entry_point_checkers() -> None:
    registry = CheckerRegistry.discover([_entry_point("stub", "tests.fakes:StubChecker")])
    assert type(registry.get("stub", "stubcheck")) is StubChecker
    assert type(registry.get(None, "stubcheck src")) is StubChecker


def test_discover_installed_entry_points() -> None:
    registry = CheckerRegistry.discover()
    assert [type(registry.get(name, "")) for name in BUILTIN_CHECKERS] == list(
        BUILTIN_CHECKERS.values()
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        pytest.param("tests.missing:Checker", "Skipping checker 'bad': failed to load", id="import"),
        pytest.param(
            "tests.fakes:make_mutant",
            "Skipping checker 'bad': tests.fakes:make_mutant is not a typemut TypeChecker subclass",
            id="not-a-class",
        ),
        pytest.param(
            "tests.fakes:StubPlugin",
            "Skipping checker 'bad': tests.fakes:StubPlugin is not a typemut TypeChecker subclass",
            id="other-class",
        ),
    ],
)
def test_discover_skips_broken_entry_points(
    value: str, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    registry = CheckerRegistry.discover([_entry_point("bad", value)])
    assert type(registry.get("bad", "mypy .")) is GenericChecker
    assert message in caplog.text
