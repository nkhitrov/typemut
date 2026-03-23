"""Tests for annotation discovery."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations


def test_discover_variable_annotation():
    source = "x: int = 5\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1
    assert annotations[0].context == AnnotationContext.VARIABLE
    assert annotations[0].code.strip() == "int"


def test_discover_parameter_annotation():
    source = "def f(x: int, y: str) -> bool:\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    params = [a for a in annotations if a.context == AnnotationContext.PARAMETER]
    assert len(params) == 2


def test_discover_return_annotation():
    source = "def f(x: int) -> str:\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    returns = [a for a in annotations if a.context == AnnotationContext.RETURN]
    assert len(returns) == 1
    assert returns[0].code.strip() == "str"


def test_discover_union():
    source = "x: int | str = 5\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1
    assert "int" in annotations[0].code
    assert "str" in annotations[0].code


def test_skip_type_ignore():
    source = "x: int = 5  # type: ignore\ny: str = 'a'\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1
    assert annotations[0].code.strip() == "str"


def test_skip_pragma_no_mutate():
    source = "x: int = 5  # pragma: no mutate\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 0


def test_skip_any_annotation():
    source = "from typing import Any\nx: Any\ndef f(a: Any) -> Any:\n    pass\ny: int\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    assert len(annotations) == 1
    assert annotations[0].code.strip() == "int"


def test_fixture_simple_unions(fixtures_dir: Path):
    source = (fixtures_dir / "simple_unions.py").read_text()
    annotations = discover_annotations(
        fixtures_dir / "simple_unions.py", source=source
    )
    assert len(annotations) > 0
    contexts = {a.context for a in annotations}
    assert AnnotationContext.PARAMETER in contexts
    assert AnnotationContext.RETURN in contexts
    assert AnnotationContext.VARIABLE in contexts
