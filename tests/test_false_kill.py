"""Tests for false-kill detection in the engine."""

from __future__ import annotations

from typemut.engine import _is_false_kill


def test_name_defined_is_false_kill():
    output = 'models.py:45: error: Name "Sequence" is not defined  [name-defined]\n'
    assert _is_false_kill(output) is True


def test_syntax_error_is_false_kill():
    output = "models.py:10: error: invalid syntax  [syntax]\n"
    assert _is_false_kill(output) is True


def test_valid_type_is_false_kill():
    output = 'models.py:20: error: Name "Foo" is not valid as a type  [valid-type]\n'
    assert _is_false_kill(output) is True


def test_attr_defined_is_real_kill():
    output = 'models.py:30: error: "Sequence[int]" has no attribute "append"  [attr-defined]\n'
    assert _is_false_kill(output) is False


def test_arg_type_is_real_kill():
    output = 'models.py:15: error: Argument 1 has incompatible type "str"; expected "int"  [arg-type]\n'
    assert _is_false_kill(output) is False


def test_assignment_is_real_kill():
    output = 'models.py:12: error: Incompatible types in assignment  [assignment]\n'
    assert _is_false_kill(output) is False


def test_return_value_is_real_kill():
    output = 'models.py:25: error: Incompatible return value type  [return-value]\n'
    assert _is_false_kill(output) is False


def test_mixed_false_and_real_is_real_kill():
    output = (
        'models.py:45: error: Name "Sequence" is not defined  [name-defined]\n'
        'models.py:30: error: "Sequence[int]" has no attribute "append"  [attr-defined]\n'
    )
    assert _is_false_kill(output) is False


def test_only_false_kill_codes():
    output = (
        'models.py:45: error: Name "Sequence" is not defined  [name-defined]\n'
        'models.py:46: error: Name "Sequence" is not valid as a type  [valid-type]\n'
    )
    assert _is_false_kill(output) is True


def test_empty_output():
    assert _is_false_kill("") is False


def test_no_error_codes():
    output = "Success: no issues found\n"
    assert _is_false_kill(output) is False
