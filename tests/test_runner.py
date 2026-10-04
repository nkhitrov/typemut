"""Tests for running shell commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.runner import CommandResult, Outcome, ShellRunner


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        pytest.param("true", CommandResult(Outcome.PASSED, ""), id="success"),
        pytest.param("echo out; exit 3", CommandResult(Outcome.FAILED, "out\n"), id="stdout"),
        pytest.param(
            "echo out; echo err >&2",
            CommandResult(Outcome.PASSED, stdout="out\n", stderr="err\n"),
            id="both-streams",
        ),
        pytest.param("sleep 5", CommandResult(Outcome.TIMED_OUT, ""), id="timeout"),
    ],
)
def test_shell_runner(command: str, expected: CommandResult) -> None:
    assert ShellRunner().run(command, timeout=1) == expected


def test_shell_runner_cwd(tmp_path: Path) -> None:
    (tmp_path / "marker").write_text("")
    assert ShellRunner().run("ls", cwd=tmp_path).output == "marker\n"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        pytest.param(CommandResult(Outcome.FAILED, stdout="out\n"), "out\n", id="stdout"),
        pytest.param(CommandResult(Outcome.FAILED, stderr="err\n"), "err\n", id="stderr"),
        pytest.param(
            CommandResult(Outcome.FAILED, stdout="out\n", stderr="err\n"),
            "out\nerr\n",
            id="both",
        ),
        pytest.param(
            CommandResult(Outcome.FAILED, stdout="out", stderr="err"),
            "out\nerr",
            id="both-unterminated",
        ),
        pytest.param(CommandResult(Outcome.TIMED_OUT), "", id="none"),
    ],
)
def test_output_shows_both_streams(result: CommandResult, expected: str) -> None:
    assert result.output == expected
