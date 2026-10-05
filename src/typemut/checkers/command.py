"""Reading the type checker invocation out of a ``test-command`` line."""

from __future__ import annotations

import itertools
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
# Runners that run a tool in the project's environment, with its Python.
_PROJECT_RUNNERS: Final = frozenset({"uv", "poetry", "pdm", "hatch", "rye"})
# Runner options that take their value as the next word (``uv run --group dev``).
_UV_VALUE_OPTIONS: Final = frozenset(
    {
        "--group",
        "--only-group",
        "--no-group",
        "--with",
        "--with-editable",
        "--with-requirements",
        "--extra",
        "--python",
        "-p",
        "--directory",
        "--project",
        "--package",
        "--env-file",
        "--from",
        "--index",
        "--config-file",
        "--cache-dir",
    }
)
_NPX_VALUE_OPTIONS: Final = frozenset({"--package", "-p"})
_RUNNER_VALUE_OPTIONS: Final = {
    "uv": _UV_VALUE_OPTIONS,
    "uvx": _UV_VALUE_OPTIONS,
    "poetry": frozenset({"--directory", "-C", "--project", "-P"}),
    "pdm": frozenset({"--project", "-p", "--venv"}),
    "pipx": frozenset({"--spec", "--python", "--pip-args"}),
    "pnpm": frozenset({"--dir", "-C", "--filter", "-F"}),
    "npx": _NPX_VALUE_OPTIONS,
    "bunx": _NPX_VALUE_OPTIONS,
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

        ``uv run mypy src`` -> ``uv run mypy --version``. The words are taken
        from the command as written, so the shell still expands ``$VAR``
        and ``~`` in them. Of the commands chained before the checker only
        ``cd`` and ``pushd`` are kept (``cd src && tox -e lint && mypy .``
        -> ``cd src && mypy --version``), so the version comes from the
        directory the checker runs in.
        """
        end = self.executable_index(executables)
        if end is None:
            return None
        start = self._command_start(end)
        return " && ".join(
            [*self._directory_changes(end), self._text(start, end + 1) + " --version"]
        )

    def python_command(self, executables: Iterable[str]) -> str | None:
        """A command printing the version of the Python the checker runs with.

        ``python3.12 -m mypy`` -> ``python3.12 --version``; a project runner
        runs the project's Python (``uv run mypy`` -> ``uv run python --version``);
        an executable run by path runs the Python next to it
        (``.venv/bin/mypy`` -> ``.venv/bin/python --version``); anything else
        gets the ``python`` on ``PATH``, as pyright uses it.
        ``cd`` and ``pushd`` before the checker are kept, as in
        :meth:`version_command`.
        """
        end = self.executable_index(executables)
        if end is None:
            return None
        start = self._command_start(end)
        words = self.words()
        prefix = words[start:end]
        name = Path(words[end]).name
        executable = self._text(end, end + 1)
        if len(prefix) >= 2 and prefix[-1] == "-m" and _PYTHON_RE.fullmatch(Path(prefix[-2]).name):
            python = self._text(start, end - 1)
        elif any(
            Path(word).name in _PROJECT_RUNNERS and following == "run"
            for word, following in itertools.pairwise(prefix)
        ):
            python = self._text(start, end) + " python"
        elif executable.endswith(f"/{name}"):
            python = executable.removesuffix(name) + "python"
        else:
            python = "python"
        return " && ".join([*self._directory_changes(end), python + " --version"])

    def _command_start(self, index: int) -> int:
        """Position of the first word of the command word *index* belongs to."""
        return max(start for start, _ in self._commands() if start <= index)

    def _directory_changes(self, end: int) -> Iterable[str]:
        """The ``cd`` and ``pushd`` commands before word *end*, as written."""
        return [
            self._text(start, start + len(command))
            for start, command in self._commands()
            if start < end and any(word in _DIRECTORY_CHANGES for word in command[:1])
        ]

    def _text(self, first: int, last: int) -> str:
        """The command as written from word *first* up to (not including) word *last*."""
        ends = self._word_ends()
        return self.command[ends[first] : ends[last]].strip()

    def _word_ends(self) -> Sequence[int]:
        """Where the words end: item *n* is the shortest start of the command with *n* words."""
        words = list(self.words())
        ends = [0]
        for length in range(1, len(self.command) + 1):
            prefix = list(CommandLine(self.command[:length]).words())
            if len(ends) <= len(words) and prefix == words[: len(ends)]:
                ends.append(length)
        return ends

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
        takes_value = _RUNNER_VALUE_OPTIONS.get(Path(word).name, frozenset())
        while 0 < length < len(words) and words[length].startswith("-"):
            length += 2 if words[length] in takes_value else 1
        return min(length, len(words))

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
