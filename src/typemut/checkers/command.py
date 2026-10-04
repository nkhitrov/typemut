"""Reading the type checker invocation out of a ``test-command`` line."""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

# Shell operators that start a new command in a command line.
_COMMAND_SEPARATORS: Final = frozenset({"&&", "||", ";", "|", "&"})


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
        """Position of the first word whose file name is one of *executables*."""
        names = frozenset(executables)
        for index, word in enumerate(self.words()):
            if Path(word).name in names:
                return index
        return None

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
