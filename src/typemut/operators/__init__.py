"""Mutation operators for type annotations."""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping
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

logger = logging.getLogger(__name__)

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

    def config_keys(self, extra: Iterable[TypeMutationOperator] = ()) -> AbstractSet[str]:
        """Keys of the registered and *extra* operators in ``[typemut.operators]``.

        The same keys select operators in ``[typemut.ignore-types]``. An
        operator without a key cannot be configured, so empty keys are left out.
        """
        keys = {operator.config_key for operator in self._operators}
        keys.update(operator.config_key for operator in extra)
        return frozenset(keys - {""})

    def enabled(
        self,
        flags: Mapping[str, bool],
        extra: Collection[TypeMutationOperator] = (),  # pragma: no mutate  (iterated twice)
    ) -> Collection[TypeMutationOperator]:
        """The registered operators, then the *extra* ones, minus those *flags* switch off.

        *flags* is ``[typemut.operators]``: ``{config key: enabled}``. Keys of
        no operator are logged as a warning and skipped.
        """
        known = self.config_keys(extra)
        for key in flags:
            if key not in known:
                logger.warning(
                    "Ignoring unknown operator %r in 'operators'. Valid keys: %s",
                    key,
                    ", ".join(sorted(known)),
                )
        operators = [operator() for operator in self._operators]
        operators.extend(extra)
        return [operator for operator in operators if flags.get(operator.config_key, True)]
