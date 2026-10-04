"""Reading the type checker invocation out of a ``test-command`` line."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final, TypeAlias

# Shell operators that start a new command in a command line.
_COMMAND_SEPARATORS: Final = frozenset({"&&", "||", ";", "|", "&"})
# Shell commands that change the working directory.
_DIRECTORY_CHANGES: Final = frozenset({"cd", "pushd"})
# Commands that run the command after them as is.
_PASS_THROUGH: Final = frozenset({"env", "exec", "time", "nice", "nohup"})
# Tools that run another tool: the words after them that do it (``uv run``,
# ``npx``). ``python -m`` is matched by _PYTHON_RE.
_RUNNERS: Final = {
    "uv": ("run",),
    "poetry": ("run",),
    "pipx": ("run",),
    "pdm": ("run",),
    "hatch": ("run",),
    "rye": ("run",),
    "pnpm": ("exec",),
    "uvx": (),
    "npx": (),
    "bunx": (),
}
# The words after an interpreter that run a module.
_PYTHON_MODULE: Final = ("-m",)
# Interpreters that run a module with ``-m``: ``python``, ``python3.12``.
_PYTHON_RE: Final = re.compile(r"python[\d.]*")
# An environment variable assignment before a command: ``MYPY_CACHE_DIR=x``.
_ASSIGNMENT_RE: Final = re.compile(r"[A-Za-z_]\w*=.*")

# One command of a command line: the position of its first word, its words.
_Command: TypeAlias = tuple[int, Sequence[str]]


class CommandLine:
    """The shell words of *command* and what they say about the checker it runs."""

    def __init__(self, command: str) -> None:
        self.command = command

    def words(self) -> Sequence[str]:
        """Shell words, with operators such as ``&&`` as separate words; none if unparsable."""
        lexer = shlex.shlex(self.command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            return list(lexer)
        except ValueError:
            return []

    def executable_index(self, executables: Iterable[str]) -> int | None:
        """Position of the first command whose file name is one of *executables*.

        The executable must be the command word, possibly after environment
        assignments and runners such as ``uv run``, ``poetry run``, ``npx``
        or ``python -m``. A matching word elsewhere is another tool's
        argument (``tox -e mypy``, ``pre-commit run mypy``) and is not the
        checker.
        """
        names = frozenset(executables)
        for start, command in self._commands():
            offset = self._prefix_length(command)
            if offset < len(command) and Path(command[offset]).name in names:
                return start + offset
        return None

    def changes_directory(
        self, executables: Iterable[str]
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether ``cd`` or ``pushd`` runs before the checker's executable.

        Without the executable in the command, anywhere in it.
        """
        words = self.words()
        end = self.executable_index(executables)
        return any(word in _DIRECTORY_CHANGES for word in words[:end])

    def version_command(self, executables: Iterable[str]) -> str | None:
        """The command up to the checker's executable, plus ``--version``.

        ``uv run mypy src`` -> ``uv run mypy --version``; commands chained
        before the checker (``cd src && mypy .``) are dropped.
        """
        words = self.words()
        end = self.executable_index(executables)
        if end is None:
            return None
        start = max(
            (index + 1 for index, word in enumerate(words[:end]) if word in _COMMAND_SEPARATORS),
            default=0,
        )
        return shlex.join([*words[start : end + 1], "--version"])

    def _commands(self) -> Iterable[_Command]:
        """The commands of the line, each with the position of its first word."""
        words = self.words()
        commands: list[_Command] = []
        start = 0
        for index, word in enumerate([*words, ";"]):
            if word in _COMMAND_SEPARATORS:
                commands.append((start, words[start:index]))
                start = index + 1
        return commands

    def _prefix_length(self, command: Sequence[str]) -> int:
        """Number of words before the one *command* actually runs.

        Environment assignments, pass-through commands and runners with
        their options; all of *command* if nothing follows them.
        """
        index = 0
        while index < len(command):
            skipped = self._prefix_words(command[index:])
            if skipped == 0:
                return index
            index += skipped
        return index

    def _prefix_words(self, words: Sequence[str]) -> int:
        """Number of leading *words* that run the words after them; 0 if none."""
        word = words[0]
        if _ASSIGNMENT_RE.fullmatch(word) or word in _PASS_THROUGH:
            return 1
        length = self._runner_length(words)
        while 0 < length < len(words) and words[length].startswith("-"):
            length += 1
        return length

    def _runner_length(self, words: Sequence[str]) -> int:
        """Number of leading *words* that start a runner (``uv run``); 0 if none."""
        name = Path(words[0]).name
        runner = _PYTHON_MODULE if _PYTHON_RE.fullmatch(name) else _RUNNERS.get(name)
        if runner is None:
            return 0
        length = 1 + len(runner)
        return length if tuple(words[1:length]) == runner else 0

    def option(self, names: Iterable[str]) -> str | None:
        """The last value of a ``--name value`` or ``--name=value`` option."""
        options = frozenset(names)
        words = self.words()
        value: str | None = None
        for index, word in enumerate(words):
            name, equals, inline = word.partition("=")
            if name not in options:
                continue
            if equals:
                value = inline
            elif index + 1 < len(words):
                value = words[index + 1]
        return value
