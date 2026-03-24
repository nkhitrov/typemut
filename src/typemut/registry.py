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
            _extract_hierarchy(tree, reg)
            _extract_literals(tree, str(f), reg)
        return reg


def _extract_hierarchy(tree: BaseNode | Leaf, reg: Registry) -> None:
    """Walk the tree and extract class inheritance info."""
    if isinstance(tree, BaseNode):
        if tree.type == "classdef":
            _process_classdef(tree, reg)
        for child in tree.children:
            _extract_hierarchy(child, reg)


def _process_classdef(node: BaseNode, reg: Registry) -> None:
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
                elif isinstance(bases_node, BaseNode) and bases_node.type == "arglist":
                    # Multiple bases — use the first one
                    for c in bases_node.children:
                        if isinstance(c, Leaf) and c.type == "name":
                            base_name = c.value
                            reg.hierarchy.setdefault(base_name, []).append(class_name)
                            reg.class_to_base[class_name] = base_name
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
