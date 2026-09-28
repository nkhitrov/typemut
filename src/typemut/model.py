"""Data types shared by discovery, operators, plugins and ignore rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from parso.python.tree import BaseNode, Leaf


class AnnotationContext(Enum):
    VARIABLE = "variable"
    PARAMETER = "parameter"
    RETURN = "return"
    TYPEVAR = "typevar"


@dataclass
class AnnotationNode:
    file: Path
    node: BaseNode | Leaf
    context: AnnotationContext
    line: int
    col: int
    code: str


@dataclass
class Mutation:
    file: str
    operator: str
    line: int
    col: int
    original: str
    mutated: str
    description: str
    # Full import line needed for the mutated type, e.g. "from abc import ABC".
    # None when no import is needed (builtins or already in scope).
    required_import: str | None = None
