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
_ALL_OFF = dict.fromkeys(_ALL_KEYS, False)


def test_all_enabled_by_default() -> None:
    operators = OperatorRegistry().enabled({})
    assert [type(op) for op in operators] == list(BUILTIN_OPERATORS)


def test_disable_specific_operator() -> None:
    names = {op.name for op in OperatorRegistry().enabled({"remove-union-member": False})}
    assert "RemoveUnionMember" not in names
    assert len(names) == 7


def test_none_enabled() -> None:
    assert OperatorRegistry().enabled(_ALL_OFF) == []


@pytest.mark.parametrize("operator", BUILTIN_OPERATORS, ids=lambda op: op.name)
def test_each_operator_individually(operator: type) -> None:
    flags = {**_ALL_OFF, operator.config_key: True}
    assert [type(op) for op in OperatorRegistry().enabled(flags)] == [operator]


def test_config_keys() -> None:
    assert OperatorRegistry().config_keys() == _ALL_KEYS


def test_config_keys_of_extra_operators() -> None:
    nameless = AddOptional()
    nameless.config_key = ""
    keys = OperatorRegistry([AddOptional]).config_keys([StubOperator(), nameless])
    assert keys == {"add-optional", "stub"}


def test_extra_operators_follow_flags() -> None:
    registry = OperatorRegistry([AddOptional])
    enabled = registry.enabled({"add-optional": False}, [StubOperator()])
    disabled = registry.enabled({"stub": False}, [StubOperator()])
    assert [type(op) for op in enabled] == [StubOperator]
    assert [type(op) for op in disabled] == [AddOptional]


def test_unknown_flag_warns(caplog: pytest.LogCaptureFixture) -> None:
    operators = OperatorRegistry([AddOptional]).enabled({"add-optionl": False})
    assert [type(op) for op in operators] == [AddOptional]
    assert "Ignoring unknown operator 'add-optionl' in 'operators'. Valid keys: add-optional" in caplog.text


def test_registry_with_custom_operators() -> None:
    registry = OperatorRegistry([StubOperator, AddOptional])
    assert registry.config_keys() == {"stub", "add-optional"}
    assert [type(op) for op in registry.enabled(_ALL_OFF)] == [StubOperator]
