"""Mutation operators for type annotations."""

from __future__ import annotations

from collections.abc import Container, Iterable
from collections.abc import Set as AbstractSet
from typing import Final

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

    def config_keys(self) -> AbstractSet[str]:
        """Keys of the registered operators in ``[typemut.operators]`` and ``[typemut.ignore-types]``."""
        return frozenset(operator.config_key for operator in self._operators)

    def enabled(self, disabled: Container[str] = ()) -> list[TypeMutationOperator]:
        """Instantiate the operators whose config key is not in *disabled*, in registration order."""
        return [operator() for operator in self._operators if operator.config_key not in disabled]
