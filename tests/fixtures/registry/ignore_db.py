"""A mapped class whose base tests/test_ignore.py's annotations do not import."""

from sqlalchemy.orm import DeclarativeBase


class UserDB(DeclarativeBase): ...
