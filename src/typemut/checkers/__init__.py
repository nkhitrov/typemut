"""Type checker plugins: everything typemut knows about the checker ``test-command`` runs."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from importlib import metadata
from typing import Final

from typemut.checkers.base import TypeChecker
from typemut.checkers.command import CommandLine
from typemut.checkers.generic import GenericChecker
from typemut.checkers.mypy import MypyChecker
from typemut.checkers.pyright import BasedPyrightChecker, PyrightChecker
from typemut.runner import CommandRunner

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP: Final = "typemut.checkers"

# ``checker`` value that detects the checker from ``test-command``.
AUTO: Final = "auto"

BUILTIN_CHECKERS: Mapping[str, type[TypeChecker]] = {
    PyrightChecker.name: PyrightChecker,
    BasedPyrightChecker.name: BasedPyrightChecker,
    MypyChecker.name: MypyChecker,
    GenericChecker.name: GenericChecker,
}


class CheckerRegistry:
    """Type checker plugins available by name for the ``checker`` config option.

    *environ* is the environment the checkers it builds run with; None means
    the current process environment.
    """

    def __init__(
        self,
        checkers: Mapping[str, type[TypeChecker]] = BUILTIN_CHECKERS,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._checkers = dict(checkers)
        self._environ = environ

    @classmethod
    def discover(
        cls,
        entry_points: Iterable[metadata.EntryPoint] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> CheckerRegistry:
        """Built-in checkers plus those installed under the ``typemut.checkers`` entry point group.

        An entry point names a :class:`TypeChecker` subclass, e.g. in ``pyproject.toml``::

            [project.entry-points."typemut.checkers"]
            pytype = "typemut_pytype:PytypeChecker"

        Entry points that fail to load or are not checkers are logged and skipped.
        """
        if entry_points is None:
            entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
        checkers = dict(BUILTIN_CHECKERS)
        for entry_point in entry_points:
            checker = cls._load_checker(entry_point)
            if checker is not None:
                checkers[entry_point.name] = checker
        return cls(checkers, environ)

    def get(
        self,
        name: str | None,
        test_command: str,
        version_command: str | None = None,
        runner: CommandRunner | None = None,
    ) -> TypeChecker:
        """The checker called *name*, or detected from *test_command* if *name* is None or auto.

        An unknown name, or a command no checker or several different
        checkers are recognised in, falls back to the generic checker with a
        warning.
        """
        if name is not None and name != AUTO:
            checker = self._named(name)
        else:
            checker = self._detect(test_command)
        return checker(test_command, version_command, runner, environ=self._environ)

    def _named(self, name: str) -> type[TypeChecker]:
        checker = self._checkers.get(name)
        if checker is None:
            logger.warning(
                "Unknown checker %r, using %r. Available checkers: %s",
                name,
                GenericChecker.name,
                ", ".join(sorted(self._checkers)),
            )
            return GenericChecker
        return checker

    def _detect(self, test_command: str) -> type[TypeChecker]:
        command = CommandLine(test_command)
        found = self._most_derived(
            [
                checker
                for checker in dict.fromkeys(self._checkers.values())
                if command.executable_index(checker.executables) is not None
            ]
        )
        if len(found) == 1:
            return found[0]
        if found:
            # The output of one checker can't be read by the other's parser.
            logger.warning(
                "test-command %r runs several type checkers (%s), using %r: "
                "set the 'checker' option to choose one",
                test_command,
                ", ".join(checker.name for checker in found),
                GenericChecker.name,
            )
            return GenericChecker
        logger.warning(
            "Could not detect the type checker in test-command %r, using %r: "
            "set the 'checker' option to choose one",
            test_command,
            GenericChecker.name,
        )
        return GenericChecker

    def _most_derived(self, found: list[type[TypeChecker]]) -> list[type[TypeChecker]]:
        """*found* without checkers a subclass sharing one of their executables replaces.

        A plugin that extends ``MypyChecker`` under another name wins over
        ``mypy`` itself; checkers with different executables all stay.
        """
        return [
            checker
            for checker in found
            if not any(
                other is not checker
                and issubclass(other, checker)
                and not frozenset(other.executables).isdisjoint(checker.executables)
                for other in found
            )
        ]

    @staticmethod
    def _load_checker(entry_point: metadata.EntryPoint) -> type[TypeChecker] | None:
        try:
            loaded = entry_point.load()
        except Exception:
            logger.warning("Skipping checker %r: failed to load", entry_point.name, exc_info=True)
            return None
        if not isinstance(loaded, type) or not issubclass(loaded, TypeChecker):
            logger.warning(
                "Skipping checker %r: %s is not a typemut TypeChecker subclass",
                entry_point.name,
                entry_point.value,
            )
            return None
        return loaded
