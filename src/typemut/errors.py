"""Errors reported to the user without a traceback."""

from __future__ import annotations


class TypemutError(Exception):
    """An expected failure: the CLI prints *message* and *details* and exits with code 1."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details
