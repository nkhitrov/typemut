"""Fixture: simple union type annotations."""

from __future__ import annotations

from typing import Literal


def process(value: int | str | float) -> bool:
    return True


def maybe_none(x: int | None) -> str:
    return str(x)


class Config:
    name: str
    value: int | str
    status: Literal["active"] | Literal["closed"] | Literal["overdue"]
