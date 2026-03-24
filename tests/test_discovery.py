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


def test_discover_typevar_with_typing_import():
    """TypeVar declarations are discovered when TypeVar is imported from typing."""
    source = 'from typing import TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    assert "TypeVar" in tvars[0].code


def test_discover_typevar_without_typing_import():
    """TypeVar declarations are NOT discovered without a typing import."""
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


def test_annassign_too_few_children():
    """annassign with less than 2 children returns None (line 45)."""
    from typemut.discovery import _get_annotation_from_annassign
    from parso.python.tree import PythonNode

    # Parse to get a real node, then manipulate its children
    import parso
    tree = parso.parse("x: int\n")
    # Find annassign node
    annassign = None
    for node in tree.children:
        if hasattr(node, 'children'):
            for child in node.children:
                if hasattr(child, 'children'):
                    for c in child.children:
                        if hasattr(c, 'type') and c.type == 'annassign':
                            annassign = c
                            break

    assert annassign is not None
    # Simulate an annassign with only 1 child by calling with modified children
    original_children = annassign.children
    annassign.children = [original_children[0]]  # only the ':'
    result = _get_annotation_from_annassign(annassign)
    assert result is None
    annassign.children = original_children  # restore


def test_tfpdef_too_few_children():
    """tfpdef with less than 3 children returns None (line 56)."""
    from typemut.discovery import _get_annotation_from_tfpdef

    import parso
    tree = parso.parse("def f(x: int):\n    pass\n")
    # Find tfpdef node
    tfpdef = None
    def find_tfpdef(node):
        nonlocal tfpdef
        if hasattr(node, 'type') and node.type == 'tfpdef':
            tfpdef = node
            return
        if hasattr(node, 'children'):
            for child in node.children:
                find_tfpdef(child)
    find_tfpdef(tree)
    assert tfpdef is not None

    # Simulate tfpdef with only 2 children
    original_children = tfpdef.children
    tfpdef.children = original_children[:2]  # name and ':'
    result = _get_annotation_from_tfpdef(tfpdef)
    assert result is None
    tfpdef.children = original_children  # restore


def test_funcdef_no_return_annotation():
    """funcdef without '->' returns None (line 69)."""
    source = "def f(x: int):\n    pass\n"
    annotations = discover_annotations(Path("test.py"), source=source)
    returns = [a for a in annotations if a.context == AnnotationContext.RETURN]
    assert len(returns) == 0


def test_line_text_out_of_range():
    """_line_text with out-of-range line returns empty string (line 76)."""
    from typemut.discovery import _line_text

    assert _line_text(["hello", "world"], 0) == ""
    assert _line_text(["hello", "world"], 3) == ""
    assert _line_text([], 1) == ""


def test_typevar_import_from_typing_with_multiple_names():
    """TypeVar imported alongside other names from typing (lines 104-119)."""
    source = 'from typing import List, TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_import_name_typing_qualified():
    """import typing (qualified import, lines 123-125)."""
    source = 'import typing\nT = typing.TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_import_from_in_simple_stmt():
    """from typing import TypeVar inside simple_stmt (lines 136-138)."""
    # When parso wraps the import_from inside a simple_stmt
    source = 'from typing import Dict, TypeVar\nT = TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1


def test_typevar_expr_stmt_no_assignment():
    """expr_stmt without '=' is not a TypeVar call (line 160)."""
    source = 'from typing import TypeVar\nTypeVar("T")\nx: int\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    # The bare TypeVar("T") call is not an assignment, so no typevar annotation
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    # It should not be discovered as a typevar
    assert len(tvars) == 0


def test_typevar_qualified_call():
    """typing.TypeVar("T") qualified call is discovered (lines 189-201)."""
    source = 'import typing\nT = typing.TypeVar("T")\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 1
    assert "TypeVar" in tvars[0].code


def test_discover_files_with_exclusions(tmp_path: Path):
    """discover_files respects exclusions and default None (lines 330, 336)."""
    from typemut.discovery import discover_files

    # Create some Python files
    (tmp_path / "foo.py").write_text("x = 1\n")
    (tmp_path / "bar.py").write_text("y = 2\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "baz.py").write_text("z = 3\n")

    # No exclusions (default None)
    files = discover_files(tmp_path)
    assert len(files) == 3

    # With exclusion pattern
    files = discover_files(tmp_path, excluded_modules=["**/bar.py"])
    assert len(files) == 2
    assert all("bar.py" not in str(f) for f in files)


def test_typevar_skip_comment():
    """TypeVar on a line with skip comment is not discovered (line 229->245)."""
    source = 'from typing import TypeVar\nT = TypeVar("T")  # type: ignore\n'
    annotations = discover_annotations(Path("test.py"), source=source)
    tvars = [a for a in annotations if a.context == AnnotationContext.TYPEVAR]
    assert len(tvars) == 0


def test_import_from_direct_child_of_tree():
    """Cover import_from as direct module child (lines 104-119)."""
    from typemut.discovery import _has_typing_typevar_import
    import parso

    # Parse and manipulate tree so import_from is a direct child
    tree = parso.parse('from typing import TypeVar\n')
    simple_stmt = tree.children[0]
    import_from = simple_stmt.children[0]
    tree.children = [import_from, tree.children[-1]]
    bare, qualified = _has_typing_typevar_import(tree)
    assert bare is True
    assert qualified is False


def test_import_from_direct_child_with_import_as_names():
    """Cover import_from with import_as_names as direct module child (lines 115-119)."""
    from typemut.discovery import _has_typing_typevar_import
    import parso

    tree = parso.parse('from typing import List, TypeVar\n')
    simple_stmt = tree.children[0]
    import_from = simple_stmt.children[0]
    tree.children = [import_from, tree.children[-1]]
    bare, qualified = _has_typing_typevar_import(tree)
    assert bare is True


def test_import_from_direct_child_no_typevar():
    """import_from direct child without TypeVar (exercises inner loop, line 104+)."""
    from typemut.discovery import _has_typing_typevar_import
    import parso

    tree = parso.parse('from typing import List\n')
    simple_stmt = tree.children[0]
    import_from = simple_stmt.children[0]
    tree.children = [import_from, tree.children[-1]]
    bare, qualified = _has_typing_typevar_import(tree)
    assert bare is False


def test_is_typevar_call_no_assignment():
    """expr_stmt with >= 3 children but no '=' returns None (line 160)."""
    from typemut.discovery import _is_typevar_call
    import parso

    # Parse T = TypeVar("T") and replace '=' with something else
    tree = parso.parse('T = TypeVar("T")\n')
    expr_stmt = tree.children[0].children[0]
    original = expr_stmt.children
    # Replace '=' with a copy of another operator
    modified = []
    for c in original:
        if hasattr(c, 'value') and c.value == '=':
            # Change value to something that's not '='
            old_val = c.value
            c.value = '+'
            modified.append(c)
        else:
            modified.append(c)
    expr_stmt.children = modified
    result = _is_typevar_call(expr_stmt, True, False)
    assert result is None
    # Restore
    for c in expr_stmt.children:
        if hasattr(c, 'value') and c.value == '+':
            c.value = '='


def test_is_typevar_call_rhs_none_guard():
    """_is_typevar_call line 165: cover the rhs-is-None defensive guard.

    Line 163 has `children[-1] if len(children) >= 3 else None`. After
    passing the len < 3 check on line 151, rhs is always children[-1].
    We use a custom list subclass to make `len >= 3` True on line 151
    but return a different length on line 163, triggering rhs = None.
    """
    from typemut.discovery import _is_typevar_call
    import parso

    tree = parso.parse('T = TypeVar("T")\n')
    expr_stmt = tree.children[0].children[0]

    class ShrinkingList(list):
        """A list that reports len < 3 on second call to len()."""
        def __init__(self, items):
            super().__init__(items)
            self._call_count = 0

        def __len__(self):
            self._call_count += 1
            if self._call_count >= 2:
                return 2  # Return < 3 on the second len() check
            return super().__len__()

    original_children = expr_stmt.children
    expr_stmt.children = ShrinkingList(original_children)
    result = _is_typevar_call(expr_stmt, True, False)
    assert result is None
    expr_stmt.children = list(original_children)


def test_extract_typevar_power_non_typevar():
    """_extract_typevar_power returns None for non-TypeVar calls (line 201)."""
    from typemut.discovery import _extract_typevar_power
    import parso

    tree = parso.parse('x = SomeFunc("T")\n')
    # Get the RHS of the assignment
    expr_stmt = tree.children[0].children[0]
    rhs = expr_stmt.children[-1]
    result = _extract_typevar_power(rhs, True, False)
    assert result is None
