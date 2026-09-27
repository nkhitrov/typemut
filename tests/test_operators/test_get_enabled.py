"""Tests for the operator registry."""

from __future__ import annotations

import pytest

from tests.fakes import StubOperator
from typemut.config import OPERATOR_KEYS, OperatorsConfig
from typemut.operators import BUILTIN_OPERATORS, OperatorRegistry
from typemut.operators.optional import AddOptional

_ALL_OFF = {key.replace("-", "_"): False for key in OPERATOR_KEYS}


def test_all_enabled_by_default() -> None:
    operators = OperatorRegistry().enabled(OperatorsConfig())
    assert [type(op) for op in operators] == list(BUILTIN_OPERATORS)


def test_disable_specific_operator() -> None:
    names = {op.name for op in OperatorRegistry().enabled(OperatorsConfig(remove_union_member=False))}
    assert "RemoveUnionMember" not in names
    assert len(names) == 7


def test_none_enabled() -> None:
    assert OperatorRegistry().enabled(OperatorsConfig(**_ALL_OFF)) == []


@pytest.mark.parametrize("operator", BUILTIN_OPERATORS, ids=lambda op: op.name)
def test_each_operator_individually(operator: type) -> None:
    flags = {**_ALL_OFF, operator.config_key.replace("-", "_"): True}
    assert [type(op) for op in OperatorRegistry().enabled(OperatorsConfig(**flags))] == [operator]


def test_operator_config_keys_match_config() -> None:
    operators = OperatorRegistry().enabled(OperatorsConfig())
    assert [op.config_key for op in operators] == list(OPERATOR_KEYS)


def test_registry_with_custom_operators() -> None:
    registry = OperatorRegistry([StubOperator, AddOptional])
    operators = registry.enabled(OperatorsConfig(**_ALL_OFF))
    assert [type(op) for op in operators] == [StubOperator]
