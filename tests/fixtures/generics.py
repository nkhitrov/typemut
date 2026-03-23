"""Fixture: generic container annotations."""

from __future__ import annotations


def get_items() -> list[int]:
    return [1, 2, 3]


def get_unique() -> set[str]:
    return {"a", "b"}


def get_frozen() -> frozenset[int]:
    return frozenset([1, 2])


def get_pair() -> tuple[int, ...]:
    return (1, 2, 3)


class DataStore:
    items: list[str]
    ids: set[int]
    mapping: dict[str, int]
