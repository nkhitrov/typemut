"""Classes the annotations of tests/test_ignore.py refer to."""

from tests.fixtures.registry.ignore_db import UserDB


class Animal: ...


class Cat(Animal): ...


__all__ = ["Animal", "Cat", "UserDB"]
