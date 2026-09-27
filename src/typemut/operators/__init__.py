"""Mutation operators for type annotations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from typemut.config import OperatorsConfig
from typemut.operators.base import TypeMutationOperator
from typemut.operators.iterator_generator import SwapIteratorGenerator
from typemut.operators.literal import RemoveLiteralMember
from typemut.operators.optional import AddOptional, RemoveOptional
from typemut.operators.union import RemoveUnionMember
from typemut.operators.variance import TypeVarVariance
from typemut.operators.widen import WidenContainerType
from typemut.operators.widen_type import WidenType

BUILTIN_OPERATORS: Final = (
    RemoveUnionMember,
    RemoveLiteralMember,
    WidenType,
    RemoveOptional,
    AddOptional,
    WidenContainerType,
    SwapIteratorGenerator,
    TypeVarVariance,
)


class OperatorRegistry:
    """The operators typemut can run, switched on and off by ``[typemut.operators]``."""

    def __init__(
        self,
        operators: Iterable[type[TypeMutationOperator]] = BUILTIN_OPERATORS,
    ) -> None:
        self._operators = tuple(operators)

    def enabled(self, config: OperatorsConfig) -> list[TypeMutationOperator]:
        """Instantiate the operators *config* enables, in registration order."""
        disabled = config.disabled_operators()
        return [operator() for operator in self._operators if operator.config_key not in disabled]
