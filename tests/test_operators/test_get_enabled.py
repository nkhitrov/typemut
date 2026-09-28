"""Tests for the operator registry."""

from __future__ import annotations

import pytest

from tests.fakes import StubOperator
from typemut.operators import BUILTIN_OPERATORS, OperatorRegistry
from typemut.operators.optional import AddOptional

_ALL_KEYS = frozenset(
    {
        "remove-union-member",
        "remove-literal-member",
        "widen-type",
        "remove-optional",
        "add-optional",
        "widen-container-type",
        "swap-iterator-generator",
        "typevar-variance",
    }
)


def test_all_enabled_by_default() -> None:
    operators = OperatorRegistry().enabled()
    assert [type(op) for op in operators] == list(BUILTIN_OPERATORS)


def test_disable_specific_operator() -> None:
    names = {op.name for op in OperatorRegistry().enabled({"remove-union-member"})}
    assert "RemoveUnionMember" not in names
    assert len(names) == 7


def test_none_enabled() -> None:
    assert OperatorRegistry().enabled(_ALL_KEYS) == []


@pytest.mark.parametrize("operator", BUILTIN_OPERATORS, ids=lambda op: op.name)
def test_each_operator_individually(operator: type) -> None:
    disabled = _ALL_KEYS - {operator.config_key}
    assert [type(op) for op in OperatorRegistry().enabled(disabled)] == [operator]


def test_config_keys() -> None:
    assert OperatorRegistry().config_keys() == _ALL_KEYS


def test_registry_with_custom_operators() -> None:
    registry = OperatorRegistry([StubOperator, AddOptional])
    assert registry.config_keys() == {"stub", "add-optional"}
    assert [type(op) for op in registry.enabled(_ALL_KEYS)] == [StubOperator]
