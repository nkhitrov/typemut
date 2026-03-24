"""Tests for get_enabled_operators()."""

from __future__ import annotations

from typemut.config import OperatorsConfig
from typemut.operators import get_enabled_operators


def test_all_enabled_by_default() -> None:
    config = OperatorsConfig()
    operators = get_enabled_operators(config)
    assert len(operators) == 11
    names = {op.name for op in operators}
    assert "RemoveUnionMember" in names
    assert "WidenContainerType" in names


def test_disable_specific_operator() -> None:
    config = OperatorsConfig(remove_union_member=False)
    operators = get_enabled_operators(config)
    names = {op.name for op in operators}
    assert "RemoveUnionMember" not in names
    assert len(operators) == 10


def test_empty_config_all_enabled() -> None:
    config = OperatorsConfig()
    operators = get_enabled_operators(config)
    assert len(operators) > 0
