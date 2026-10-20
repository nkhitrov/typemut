"""Per-operator ignore rules for library types and for fields of class hierarchies.

Configured in ``typemut.toml``::

    [typemut.ignore-types]
    all = ["django.db.models.*"]
    add-optional = ["sqlalchemy.orm.Mapped"]

    [typemut.ignore-classes]
    add-optional = ["myproject.api.BaseResponse"]

Patterns are ``fnmatch`` globs matched against qualified names: for types, the
name a type is imported under (``sqlalchemy.orm.Mapped``), not where it is
defined. An operator skips every annotation that references one of its ignored
types, and drops mutations that would introduce one (e.g. WidenType to a base
class from an ignored library). It also skips the fields (class-level
annotations) of classes that are, or inherit from, one of its ignored classes.
Plugins see annotations first and are not affected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from fnmatch import fnmatchcase

from parso.python.tree import BaseNode, Leaf, Module

from typemut.config import ALL_OPERATORS
from typemut.hierarchy import ClassHierarchy, ClassNames
from typemut.imports import ImportInjector, ModuleImports
from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.nodes import NodeSource

_FROM_IMPORT_RE = re.compile(r"^from\s+(\S+)\s+import\s+(\w+)")

# id(module tree) -> (module tree, {local name: qualified name})
_NamesCache = dict[int, tuple[Module, dict[str, str]]]


class OperatorPatterns:
    """Qualified name patterns per operator config key (``add-optional``, ...)."""

    def __init__(self, patterns: Mapping[str, Iterable[str]] | None = None) -> None:
        self._patterns = {key: tuple(values) for key, values in (patterns or {}).items()}

    def patterns_for(self, operator_key: str) -> tuple[str, ...]:
        """Patterns that apply to an operator: the ``all`` ones plus its own."""
        return self._patterns.get(ALL_OPERATORS, ()) + self._patterns.get(operator_key, ())

    def matches(self, qualified_name: str, operator_key: str) -> bool:
        return any(
            fnmatchcase(qualified_name, pattern) for pattern in self.patterns_for(operator_key)
        )


class IgnoredTypes(OperatorPatterns, NodeSource):
    """Ignored type patterns per operator config key."""

    def __init__(
        self,
        patterns: Mapping[str, Iterable[str]] | None = None,
        imports: ModuleImports | None = None,
        injector: ImportInjector | None = None,
    ) -> None:
        super().__init__(patterns)
        self._imports = imports or ModuleImports()
        self._injector = injector or ImportInjector()
        self._names: _NamesCache = {}

    def is_ignored(self, annotation: AnnotationNode, operator_key: str) -> bool:
        """Whether the annotation references a type the operator must not touch."""
        if not self.patterns_for(operator_key):
            return False
        names = self._imported_names(annotation)
        qualified = (self._qualify(dotted, names) for dotted in self._dotted_names(annotation.node))
        return any(name is not None and self.matches(name, operator_key) for name in qualified)

    def drops(self, mutation: Mutation, annotation: AnnotationNode, operator_key: str) -> bool:
        """Whether the mutation introduces a type the operator must not use."""
        if not self.patterns_for(operator_key):
            return False
        qualified = self._introduced_type(mutation, self._imported_names(annotation))
        return qualified is not None and self.matches(qualified, operator_key)

    def _imported_names(self, annotation: AnnotationNode) -> dict[str, str]:
        root: BaseNode | Leaf = annotation.node
        while root.parent is not None:
            root = root.parent
        if not isinstance(root, Module):
            return {}
        cached = self._names.get(id(root))
        if cached is None or cached[0] is not root:
            cached = (root, self._imports.names(root, self._imports.package_of(annotation.file)))
            self._names[id(root)] = cached
        return cached[1]

    def _dotted_names(self, node: BaseNode | Leaf) -> Iterator[str]:
        """Yield every type reference in an annotation: ``int``, ``orm.Mapped``, ..."""
        if isinstance(node, Leaf):
            if node.type == "name":
                yield node.value
            return
        children = node.children
        head = self._dotted_head(node)
        if head is not None:
            yield ".".join(head)
            children = children[len(head) :]
        for child in children:
            yield from self._dotted_names(child)

    def _introduced_type(self, mutation: Mutation, names: Mapping[str, str]) -> str | None:
        """Qualified name of the type a mutation brings into the annotation, if known."""
        if mutation.required_import is not None:
            match = _FROM_IMPORT_RE.match(mutation.required_import.strip())
            return f"{match.group(1)}.{match.group(2)}" if match else None
        type_name = self._injector.type_name(mutation.mutated)
        qualified = self._qualify(type_name, names)
        if qualified is not None:
            return qualified
        module = self._injector.source_module(type_name)
        return f"{module}.{type_name}" if module else None

    def _qualify(self, dotted: str, names: Mapping[str, str]) -> str | None:
        """Resolve ``orm.Mapped`` to ``sqlalchemy.orm.Mapped`` via the file's imports."""
        head, _, tail = dotted.partition(".")
        base = names.get(head)
        if base is None:
            return None
        return f"{base}.{tail}" if tail else base


class IgnoredClasses(OperatorPatterns):
    """Ignored class patterns per operator config key: their fields are not mutated.

    A field is ignored when the class it is declared in, or any of its bases
    known from *hierarchy* (the project's classes), matches a pattern.
    Parameters and return types of methods are mutated as usual.
    """

    def __init__(
        self,
        patterns: Mapping[str, Iterable[str]] | None = None,
        hierarchy: ClassHierarchy | None = None,
        names: ClassNames | None = None,
    ) -> None:
        super().__init__(patterns)
        self._hierarchy = hierarchy or ClassHierarchy()
        self._names = names or ClassNames()

    def is_ignored(self, annotation: AnnotationNode, operator_key: str) -> bool:
        """Whether the annotation is a field of a class the operator must not touch."""
        if annotation.context is not AnnotationContext.VARIABLE:
            return False
        if not self.patterns_for(operator_key):
            return False
        owner = self._names.enclosing_class(annotation.node)
        if owner is None:
            return False
        lineage = self._hierarchy.lineage(
            self._names.qualified_name(owner, annotation.file),
            self._names.bases(owner, annotation.file),
        )
        return any(self.matches(name, operator_key) for name in lineage)
