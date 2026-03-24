"""Mutation operators for type annotations."""

from __future__ import annotations

from typemut.config import OperatorsConfig
from typemut.operators.base import TypeMutationOperator


def get_enabled_operators(config: OperatorsConfig) -> list[TypeMutationOperator]:
    """Return list of enabled operators based on config."""
    operators: list[TypeMutationOperator] = []

    if config.remove_union_member:
        from typemut.operators.union import RemoveUnionMember

        operators.append(RemoveUnionMember())
    if config.swap_literal_value:
        from typemut.operators.literal import SwapLiteralValue

        operators.append(SwapLiteralValue())
    if config.swap_sibling_type:
        from typemut.operators.sibling import SwapSiblingType

        operators.append(SwapSiblingType())
    if config.strip_annotated:
        from typemut.operators.annotated import StripAnnotated

        operators.append(StripAnnotated())
    if config.remove_optional:
        from typemut.operators.optional import RemoveOptional

        operators.append(RemoveOptional())
    if config.add_optional:
        from typemut.operators.optional import AddOptional

        operators.append(AddOptional())
    if config.swap_container_type:
        from typemut.operators.container import SwapContainerType

        operators.append(SwapContainerType())
    if config.tuple_ellipsis:
        from typemut.operators.tuple_ellipsis import TupleEllipsis

        operators.append(TupleEllipsis())
    if config.widen_container_type:
        from typemut.operators.widen import WidenContainerType

        operators.append(WidenContainerType())
    if config.swap_iterator_generator:
        from typemut.operators.iterator_generator import SwapIteratorGenerator

        operators.append(SwapIteratorGenerator())
    if config.typevar_variance:
        from typemut.operators.variance import TypeVarVariance

        operators.append(TypeVarVariance())

    return operators
