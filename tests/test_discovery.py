"""Tests for annotation discovery."""

from __future__ import annotations

from pathlib import Path

from typemut.discovery import AnnotationContext, discover_annotations, discover_files


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


def test_discover_typevar_with_typing_import():
    source = 'from typing import TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    assert "TypeVar" in tvars[0].code


def test_discover_typevar_without_typing_import():
    source = 'T = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


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


def test_funcdef_no_return_annotation():
    source = "def f(x: int):\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    returns = [a for a in annotations if a.context == AnnotationContext.RETURN]
    assert len(returns) == 0


def test_typevar_import_from_typing_with_multiple_names():
    source = 'from typing import List, TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_import_name_typing_qualified():
    source = 'import typing\nT = typing.TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_import_from_in_simple_stmt():
    # When parso wraps the import_from inside a simple_stmt
    source = 'from typing import Dict, TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_expr_stmt_no_assignment():
    source = 'from typing import TypeVar\nTypeVar("T")\nx: int\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


def test_typevar_qualified_call():
    source = 'import typing\nT = typing.TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    assert "TypeVar" in tvars[0].code


def test_discover_files_with_exclusions(tmp_path: Path):
    (tmp_path / "foo.py").write_text("x = 1\n")
    (tmp_path / "bar.py").write_text("y = 2\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "baz.py").write_text("z = 3\n")

    files = discover_files(tmp_path)
    assert len(files) == 3

    files = discover_files(tmp_path, excluded_modules=["**/bar.py"])
    assert len(files) == 2
    assert all("bar.py" not in str(f) for f in files)


def test_typevar_skip_comment():
    source = 'from typing import TypeVar\nT = TypeVar("T")  # type: ignore\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0
