"""Tests for StripAnnotated operator."""

from __future__ import annotations

import pytest

from typemut.operators.annotated import StripAnnotated

from tests.conftest import assert_mutations


def test_strip_annotated() -> None:
    source = 'from typing import Annotated\nx: Annotated[str, "metadata"]\n'
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["str"],
        annotation_filter="Annotated",
    )
    assert "StripAnnotated" in mutations[0].operator


def test_no_strip_for_plain_type() -> None:
    assert_mutations("x: int\n", StripAnnotated, expected=[])


def test_strip_annotated_with_complex_type_and_metadata() -> None:
    """Annotated with a complex inner type and metadata."""
    source = 'from typing import Annotated\nx: Annotated[list[int], "metadata"]\n'
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["list[int]"],
        annotation_filter="Annotated",
    )
    assert mutations[0].operator == "StripAnnotated"


def test_strip_annotated_complex_type_no_metadata() -> None:
    """Annotated with a complex inner type and no metadata (line 76-77).

    The single subscript is a BaseNode (atom_expr), not a subscriptlist.
    """
    source = "from typing import Annotated\nx: Annotated[list[int]]\n"
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["list[int]"],
        annotation_filter="Annotated",
    )
    assert mutations[0].operator == "StripAnnotated"


def test_strip_annotated_no_metadata() -> None:
    """Annotated[X] with no metadata — single name subscript (line 74)."""
    source = "from typing import Annotated\nx: Annotated[str]\n"
    mutations = assert_mutations(
        source,
        StripAnnotated,
        expected=["str"],
        annotation_filter="Annotated",
    )
    assert len(mutations) == 1


def test_non_annotated_recurse() -> None:
    """Non-Annotated nodes recurse into children (lines 58-59)."""
    source = 'from typing import Annotated\nx: list[Annotated[str, "meta"]]\n'
    from pathlib import Path
    from typemut.discovery import discover_annotations, AnnotationContext
    from typemut.registry import Registry

    annotations = discover_annotations(Path("test.py"), source=source)
    op = StripAnnotated()
    mutations = op.find_mutations(annotations[0].node, AnnotationContext.VARIABLE, Registry())
    assert len(mutations) == 1
    assert mutations[0].mutated == "str"


def test_annotated_subscriptlist_skip_comma() -> None:
    """subscriptlist processing skips commas (line 71)."""
    from typemut.operators.annotated import _get_first_subscript_arg
    import parso

    # Parse Annotated[int, "field"] and manipulate subscriptlist
    # to have comma as first child, exercising the comma skip
    tree = parso.parse('from typing import Annotated\nx: Annotated[int, "field"]\n')

    # Find the Annotated trailer
    def find_annotated_trailer(node):
        if hasattr(node, 'children'):
            for i, c in enumerate(node.children):
                if hasattr(c, 'value') and c.value == 'Annotated':
                    if i + 1 < len(node.children):
                        return node.children[i + 1]
            for c in node.children:
                result = find_annotated_trailer(c)
                if result:
                    return result
        return None

    trailer = find_annotated_trailer(tree)
    assert trailer is not None

    # Find the subscriptlist
    subscriptlist = None
    for c in trailer.children:
        if hasattr(c, 'type') and c.type == 'subscriptlist':
            subscriptlist = c
            break
    assert subscriptlist is not None

    # Rearrange subscriptlist children to put comma first
    original = subscriptlist.children
    comma = [c for c in original if hasattr(c, 'value') and c.value == ','][0]
    non_commas = [c for c in original if not (hasattr(c, 'value') and c.value == ',')]
    subscriptlist.children = [comma] + non_commas
    result = _get_first_subscript_arg(trailer)
    assert result is not None
    subscriptlist.children = original  # restore


def test_get_first_subscript_arg_returns_none() -> None:
    """_get_first_subscript_arg returns None for empty trailer (line 78)."""
    from typemut.operators.annotated import _get_first_subscript_arg
    import parso

    # Parse to get a real trailer, then empty it
    tree = parso.parse('from typing import Annotated\nx: Annotated[str]\n')
    def find_annotated_trailer(node):
        if hasattr(node, 'children'):
            for i, c in enumerate(node.children):
                if hasattr(c, 'value') and c.value == 'Annotated':
                    if i + 1 < len(node.children):
                        return node.children[i + 1]
            for c in node.children:
                result = find_annotated_trailer(c)
                if result:
                    return result
        return None

    trailer = find_annotated_trailer(tree)
    original = trailer.children
    # Only keep [ and ]
    trailer.children = [original[0], original[-1]]
    result = _get_first_subscript_arg(trailer)
    assert result is None
    trailer.children = original
