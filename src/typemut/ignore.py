"""Per-operator ignore rules for types from specific libraries.

Configured in ``typemut.toml``::

    [typemut.ignore-types]
    all = ["django.db.models.*"]
    add-optional = ["sqlalchemy.orm.Mapped"]

Patterns are ``fnmatch`` globs matched against the qualified name a type is
imported under (``sqlalchemy.orm.Mapped``), not where it is defined.
An operator skips every annotation that references one of its ignored types,
and drops mutations that would introduce one (e.g. WidenType to a base class
from an ignored library). Plugins see annotations first and are not affected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from fnmatch import fnmatchcase

from parso.python.tree import BaseNode, Leaf, Module

from typemut.config import ALL_OPERATORS
from typemut.discovery import AnnotationNode
from typemut.imports import IMPORT_SOURCES, extract_type_name, imported_names, package_of
from typemut.operators.base import Mutation

_FROM_IMPORT_RE = re.compile(r"^from\s+(\S+)\s+import\s+(\w+)")

# id(module tree) -> (module tree, {local name: qualified name})
_NamesCache = dict[int, tuple[Module, dict[str, str]]]


class IgnoredTypes:
    """Ignored type patterns per operator config key (``add-optional``, ...)."""

    def __init__(self, patterns: Mapping[str, Iterable[str]] | None = None) -> None:
        self._patterns = {key: tuple(values) for key, values in (patterns or {}).items()}
        self._names: _NamesCache = {}

    def patterns_for(self, operator_key: str) -> tuple[str, ...]:
        """Patterns that apply to an operator: the ``all`` ones plus its own."""
        return self._patterns.get(ALL_OPERATORS, ()) + self._patterns.get(operator_key, ())

    def matches(self, qualified_name: str, operator_key: str) -> bool:
        return any(
            fnmatchcase(qualified_name, pattern) for pattern in self.patterns_for(operator_key)
        )

    def is_ignored(self, annotation: AnnotationNode, operator_key: str) -> bool:
        """Whether the annotation references a type the operator must not touch."""
        if not self.patterns_for(operator_key):
            return False
        names = self._imported_names(annotation)
        qualified = (_qualify(dotted, names) for dotted in _dotted_names(annotation.node))
        return any(name is not None and self.matches(name, operator_key) for name in qualified)

    def drops(self, mutation: Mutation, annotation: AnnotationNode, operator_key: str) -> bool:
        """Whether the mutation introduces a type the operator must not use."""
        if not self.patterns_for(operator_key):
            return False
        qualified = _introduced_type(mutation, self._imported_names(annotation))
        return qualified is not None and self.matches(qualified, operator_key)

    def _imported_names(self, annotation: AnnotationNode) -> dict[str, str]:
        root: BaseNode | Leaf = annotation.node
        while root.parent is not None:
            root = root.parent
        if not isinstance(root, Module):
            return {}
        cached = self._names.get(id(root))
        if cached is None or cached[0] is not root:
            cached = (root, imported_names(root, package_of(annotation.file)))
            self._names[id(root)] = cached
        return cached[1]


def _dotted_names(node: BaseNode | Leaf) -> Iterator[str]:
    """Yield every type reference in an annotation: ``int``, ``orm.Mapped``, ..."""
    if isinstance(node, Leaf):
        if node.type == "name":
            yield node.value
        return
    children = node.children
    head = _dotted_head(node)
    if head is not None:
        yield ".".join(head)
        children = children[len(head) :]
    for child in children:
        yield from _dotted_names(child)


def _dotted_head(node: BaseNode) -> list[str] | None:
    """Return ``["orm", "Mapped"]`` for ``orm.Mapped[...]``, None if not a name chain."""
    head = node.children[0]
    if node.type not in {"atom_expr", "power"} or not isinstance(head, Leaf) or head.type != "name":
        return None
    parts = [head.value]
    for trailer in node.children[1:]:
        attribute = _attribute_name(trailer)
        if attribute is None:
            break
        parts.append(attribute)
    return parts


def _attribute_name(node: BaseNode | Leaf) -> str | None:
    """Return ``x`` for a ``.x`` trailer, None for anything else."""
    if isinstance(node, Leaf) or node.type != "trailer":
        return None
    dot, name = node.children[0], node.children[-1]
    if isinstance(dot, Leaf) and dot.value == "." and isinstance(name, Leaf):
        return name.value
    return None


def _introduced_type(mutation: Mutation, names: Mapping[str, str]) -> str | None:
    """Qualified name of the type a mutation brings into the annotation, if known."""
    if mutation.required_import is not None:
        match = _FROM_IMPORT_RE.match(mutation.required_import.strip())
        return f"{match.group(1)}.{match.group(2)}" if match else None
    type_name = extract_type_name(mutation.mutated)
    qualified = _qualify(type_name, names)
    if qualified is not None:
        return qualified
    module = IMPORT_SOURCES.get(type_name)
    return f"{module}.{type_name}" if module else None


def _qualify(dotted: str, names: Mapping[str, str]) -> str | None:
    """Resolve ``orm.Mapped`` to ``sqlalchemy.orm.Mapped`` via the file's imports."""
    head, _, tail = dotted.partition(".")
    base = names.get(head)
    if base is None:
        return None
    return f"{base}.{tail}" if tail else base
