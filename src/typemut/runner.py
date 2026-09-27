"""Running shell commands: the configured type checker and git."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class Outcome(Enum):
    PASSED = "passed"  # exit code 0
    FAILED = "failed"  # any other exit code
    TIMED_OUT = "timed-out"


@dataclass(frozen=True)
class CommandResult:
    outcome: Outcome
    # stderr, or stdout when stderr is empty
    output: str


class CommandRunner(Protocol):
    """Runs a shell command; the seam between typemut and the processes it starts."""

    def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        """Run *command* in a shell and wait for it to finish."""
        ...


class ShellRunner:
    """Runs commands with :func:`subprocess.run` in a shell."""

    def run(
        self,
        command: str,
        *,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                timeout=timeout,
                capture_output=True,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(Outcome.TIMED_OUT, "")
        output = completed.stderr.decode(errors="replace")
        if not output:
            output = completed.stdout.decode(errors="replace")
        outcome = Outcome.PASSED if completed.returncode == 0 else Outcome.FAILED
        return CommandResult(outcome, output)
