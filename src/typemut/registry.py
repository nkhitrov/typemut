"""Build class hierarchy and literal pool from source files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Leaf


@dataclass
class Registry:
    """Stores class hierarchy and literal value pool across modules."""

    # {base_class: [child1, child2, ...]}
    hierarchy: dict[str, list[str]] = field(default_factory=dict)

    # {class_name: base_class}
    class_to_base: dict[str, str] = field(default_factory=dict)

    # {type_name: "from module import type_name"} — import lines for base classes
    # Populated by scanning imports in files that define child classes.
    base_import_lines: dict[str, str] = field(default_factory=dict)

    # Set of all Literal string/int values found
    literal_pool: set[str] = field(default_factory=set)

    # Per-file literal pools: {file_path: {value1, value2, ...}}
    file_literal_pools: dict[str, set[str]] = field(default_factory=dict)

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

    def get_file_literals(self, file_path: str) -> set[str]:
        """Get all literal values found in the given file."""
        return self.file_literal_pools.get(file_path, set())

    @classmethod
    def from_files(cls, files: list[Path]) -> Registry:
        reg = cls()
        for f in files:
            try:
                source = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            tree = parso.parse(source)
            file_imports = _extract_imports(tree)
            _extract_hierarchy(tree, reg, file_imports)
            _extract_literals(tree, str(f), reg)
        return reg


def _extract_imports(tree: BaseNode) -> dict[str, str]:
    """Extract all ``from X import Y`` mappings from the module-level AST.

    Returns {name: "from module import name"} for each imported name.
    """
    imports: dict[str, str] = {}

    def _visit_import_from(node: BaseNode) -> None:
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
                        imports[child.value] = f"from {module} import {child.value}"
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
                            imports[sub.value] = f"from {module} import {sub.value}"
                        elif isinstance(sub, BaseNode) and sub.type == "import_as_name":
                            # from X import Y as Z — use the original name Y
                            for s in sub.children:
                                if isinstance(s, Leaf) and s.type == "name":
                                    imports[s.value] = f"from {module} import {s.value}"
                                    break

    for child in tree.children:
        if isinstance(child, BaseNode):
            if child.type == "import_from":
                _visit_import_from(child)
            elif child.type == "simple_stmt":
                for sub in child.children:
                    if isinstance(sub, BaseNode) and sub.type == "import_from":
                        _visit_import_from(sub)

    return imports


def _extract_hierarchy(
    tree: BaseNode | Leaf,
    reg: Registry,
    file_imports: dict[str, str],
) -> None:
    """Walk the tree and extract class inheritance info."""
    if isinstance(tree, BaseNode):
        if tree.type == "classdef":
            _process_classdef(tree, reg, file_imports)
        for child in tree.children:
            _extract_hierarchy(child, reg, file_imports)


def _process_classdef(
    node: BaseNode,
    reg: Registry,
    file_imports: dict[str, str],
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
                    base_name = bases_node.value
                    reg.hierarchy.setdefault(base_name, []).append(class_name)
                    reg.class_to_base[class_name] = base_name
                    if base_name in file_imports:
                        reg.base_import_lines.setdefault(base_name, file_imports[base_name])
                elif isinstance(bases_node, BaseNode) and bases_node.type == "arglist":
                    # Multiple bases — use the first one
                    for c in bases_node.children:
                        if isinstance(c, Leaf) and c.type == "name":
                            base_name = c.value
                            reg.hierarchy.setdefault(base_name, []).append(class_name)
                            reg.class_to_base[class_name] = base_name
                            if base_name in file_imports:
                                reg.base_import_lines.setdefault(base_name, file_imports[base_name])
                            break
            break


def _extract_literals(
    tree: BaseNode | Leaf, file_path: str, reg: Registry
) -> None:
    """Find Literal[...] values in the tree."""
    if isinstance(tree, Leaf):
        return

    if isinstance(tree, BaseNode):
        # Look for pattern: Name('Literal') trailer('[' subscript ']')
        children = tree.children
        for i, child in enumerate(children):
            if (
                isinstance(child, Leaf)
                and child.value == "Literal"
                and i + 1 < len(children)
            ):
                trailer = children[i + 1]
                if isinstance(trailer, BaseNode) and trailer.type == "trailer":
                    _collect_literal_values(trailer, file_path, reg)

        for child in children:
            _extract_literals(child, file_path, reg)


def _collect_literal_values(
    trailer: BaseNode, file_path: str, reg: Registry
) -> None:
    """Extract values from a Literal[...] trailer node."""
    for child in trailer.children:
        if isinstance(child, Leaf):
            if child.type == "string" or child.type == "number":
                val = child.value
                reg.literal_pool.add(val)
                reg.file_literal_pools.setdefault(file_path, set()).add(val)
        elif isinstance(child, BaseNode):
            # Could be subscriptlist with multiple values
            if child.type == "subscriptlist" or child.type == "subscript":
                for sub in child.children:
                    if isinstance(sub, Leaf) and sub.type in ("string", "number"):
                        reg.literal_pool.add(sub.value)
                        reg.file_literal_pools.setdefault(file_path, set()).add(
                            sub.value
                        )
