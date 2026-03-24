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


def test_none_enabled() -> None:
    """All operators disabled returns empty list."""
    config = OperatorsConfig(
        remove_union_member=False,
        swap_literal_value=False,
        widen_type=False,
        strip_annotated=False,
        remove_optional=False,
        add_optional=False,
        swap_container_type=False,
        tuple_ellipsis=False,
        widen_container_type=False,
        swap_iterator_generator=False,
        typevar_variance=False,
    )
    operators = get_enabled_operators(config)
    assert len(operators) == 0


def test_each_operator_individually() -> None:
    """Each operator can be enabled individually, covering all branches."""
    operator_flags = [
        ("remove_union_member", "RemoveUnionMember"),
        ("swap_literal_value", "SwapLiteralValue"),
        ("widen_type", "WidenType"),
        ("strip_annotated", "StripAnnotated"),
        ("remove_optional", "RemoveOptional"),
        ("add_optional", "AddOptional"),
        ("swap_container_type", "SwapContainerType"),
        ("tuple_ellipsis", "TupleEllipsis"),
        ("widen_container_type", "WidenContainerType"),
        ("swap_iterator_generator", "SwapIteratorGenerator"),
        ("typevar_variance", "TypeVarVariance"),
    ]
    for flag, name in operator_flags:
        # Disable all, enable only this one
        kwargs = {f: False for f, _ in operator_flags}
        kwargs[flag] = True
        config = OperatorsConfig(**kwargs)
        operators = get_enabled_operators(config)
        assert len(operators) == 1, f"Expected 1 operator for {flag}"
        assert operators[0].name == name
