"""Build class hierarchy from source files."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Leaf


@dataclass
class Registry:
    """Stores class hierarchy across modules."""

    # {base_class: [child1, child2, ...]}
    hierarchy: dict[str, list[str]] = field(default_factory=dict)

    # {class_name: base_class}
    class_to_base: dict[str, str] = field(default_factory=dict)

    # {type_name: "from module import type_name"} — import lines for base classes
    # Populated by scanning imports in files that define child classes.
    base_import_lines: dict[str, str] = field(default_factory=dict)

    def get_siblings(self, class_name: str) -> list[str]:
        """Get sibling classes (same base, excluding self)."""
        base = self.class_to_base.get(class_name)
        if base is None:
            return []
        return [c for c in self.hierarchy.get(base, []) if c != class_name]

    def get_base(self, class_name: str) -> str | None:
        """Get the base class for a given class."""
        return self.class_to_base.get(class_name)

    def get_base_import_line(self, base_name: str) -> str | None:
        """Get the import line needed to bring *base_name* into scope."""
        return self.base_import_lines.get(base_name)


# Module-level compound statements whose bodies may hold imports, e.g.
# ``try: ... except ImportError: ...`` or ``if TYPE_CHECKING: ...``.
# ``suite`` is the indented body of any of their branches.
_CONDITIONAL_BLOCK_TYPES = frozenset({"try_stmt", "if_stmt", "suite"})


class RegistryBuilder:
    """Builds a :class:`Registry` from the class definitions in a set of files."""

    def build(self, files: Iterable[Path]) -> Registry:
        """Registry of the classes defined in *files*; unreadable files are skipped."""
        reg = Registry()
        for f in files:
            try:
                source = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            tree = parso.parse(source)
            file_imports = self._extract_imports(tree)
            self._extract_hierarchy(tree, reg, file_imports)
        return reg

    def _extract_imports(self, tree: BaseNode) -> dict[str, str]:
        """Extract all ``from X import Y`` mappings from the module-level AST.

        Imports inside module-level ``try``/``if`` blocks are included; imports
        inside function or class bodies are not. The first occurrence of a name
        wins, so ``try:`` imports take precedence over ``except`` fallbacks.

        Returns {name: "from module import name"} for each imported name.
        """
        imports: dict[str, str] = {}
        for node in self._import_froms(tree):
            self._add_import_from(node, imports)
        return imports

    def _add_import_from(self, node: BaseNode, imports: dict[str, str]) -> None:
        """Process ``from module import name1, name2, ...``."""
        # Children: 'from' module 'import' names...
        module_parts: list[str] = []
        found_import = False
        for child in node.children:
            if isinstance(child, Leaf):
                if child.value == "from":
                    continue
                elif child.value == "import":
                    found_import = True
                    continue
                elif not found_import:
                    # Part of the module path (including dots)
                    module_parts.append(child.value)
                else:
                    # Imported name
                    if child.type == "name":
                        module = "".join(module_parts)
                        imports.setdefault(child.value, f"from {module} import {child.value}")
            elif isinstance(child, BaseNode):
                if not found_import:
                    # Dotted module name
                    for sub in child.children:
                        if isinstance(sub, Leaf):
                            module_parts.append(sub.value)
                else:
                    # import_as_names or similar
                    module = "".join(module_parts)
                    for sub in child.children:
                        if isinstance(sub, Leaf) and sub.type == "name":
                            imports.setdefault(sub.value, f"from {module} import {sub.value}")
                        elif isinstance(sub, BaseNode) and sub.type == "import_as_name":
                            # from X import Y as Z — use the original name Y
                            for s in sub.children:
                                if isinstance(s, Leaf) and s.type == "name":
                                    imports.setdefault(s.value, f"from {module} import {s.value}")
                                    break

    def _import_froms(self, node: BaseNode) -> Iterator[BaseNode]:
        """Yield ``import_from`` nodes, descending into try/if blocks but not def/class."""
        for child in node.children:
            if not isinstance(child, BaseNode):
                continue
            if child.type == "import_from":
                yield child
            elif child.type == "simple_stmt":
                for sub in child.children:
                    if isinstance(sub, BaseNode) and sub.type == "import_from":
                        yield sub
            elif child.type in _CONDITIONAL_BLOCK_TYPES:
                yield from self._import_froms(child)

    def _extract_hierarchy(
        self,
        tree: BaseNode | Leaf,
        reg: Registry,
        file_imports: Mapping[str, str],
    ) -> None:
        """Walk the tree and extract class inheritance info."""
        if isinstance(tree, BaseNode):
            if tree.type == "classdef":
                self._process_classdef(tree, reg, file_imports)
            for child in tree.children:
                self._extract_hierarchy(child, reg, file_imports)

    def _process_classdef(
        self,
        node: BaseNode,
        reg: Registry,
        file_imports: Mapping[str, str],
    ) -> None:
        """Extract class Name(Base) pattern from a classdef node."""
        children = node.children
        # classdef: 'class' NAME ['(' arglist ')'] ':'
        if len(children) < 3:
            return

        class_name = children[1].value if isinstance(children[1], Leaf) else None
        if class_name is None:
            return

        # Find the arglist (base classes)
        for child in children:
            if isinstance(child, Leaf) and child.value == "(":
                idx = children.index(child)
                if idx + 1 < len(children):
                    bases_node = children[idx + 1]
                    if isinstance(bases_node, Leaf) and bases_node.value != ")":
                        # Single base class
                        self._register(reg, class_name, bases_node.value, file_imports)
                    elif isinstance(bases_node, BaseNode) and bases_node.type == "arglist":
                        # Multiple bases — use the first one
                        for c in bases_node.children:
                            if isinstance(c, Leaf) and c.type == "name":
                                self._register(reg, class_name, c.value, file_imports)
                                break
                break

    def _register(
        self, reg: Registry, class_name: str, base_name: str, file_imports: Mapping[str, str]
    ) -> None:
        """Record *class_name* as a child of *base_name*, with the import of the base."""
        reg.hierarchy.setdefault(base_name, []).append(class_name)
        reg.class_to_base[class_name] = base_name
        if base_name in file_imports:
            reg.base_import_lines.setdefault(base_name, file_imports[base_name])
