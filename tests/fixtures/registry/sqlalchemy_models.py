"""Classes the annotations of tests/test_plugins/test_sqlalchemy.py refer to."""

from enum import StrEnum

from sqlalchemy.orm import DeclarativeBase


class BaseDB(DeclarativeBase): ...


class UserDB(BaseDB): ...


class StatusEnum(StrEnum): ...
