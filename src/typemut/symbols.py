"""Static resolution of names to qualified names across project modules.

Answers, with parso alone and without importing user code:

- which class the object bound to a name is an instance of
  (``app = FastAPI()`` -> ``fastapi.FastAPI``);
- whether a class inherits from given classes, also through project classes
  defined in other modules (``class Api(FastAPI)``).

Names follow imports into project modules, re-exports included. Only
``name = Class(...)`` and ``name: Class`` bindings (and annotated function
parameters) have a known class; anything else (a factory call, an attribute
of ``self``, a star import) is unknown.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Function, Leaf, Module, Name

from typemut.imports import imported_names, package_of

# Nested scopes: names bound inside them are not visible outside.
SCOPES = frozenset(("funcdef", "classdef", "lambdef"))

# {bound name: dotted name of its class as written, None if not an instance / unknown}
Bindings = dict[str, str | None]


class SymbolResolver:
    """Resolve names in project files; parsed modules are cached per resolver."""

    def __init__(self) -> None:
        self._trees: dict[Path, Module | None] = {}
        self._bindings: dict[Path, Bindings] = {}
        self._imports: dict[Path, dict[str, str]] = {}

    def instance_class(self, dotted: str, node: BaseNode | Leaf, file: Path) -> str | None:
        """Qualified class of the object *dotted* (``app``, ``api.router``) refers to at *node*.

        *node* must belong to the parsed tree of *file*.
        """
        file = file.resolve()
        self._set_tree(file, _root(node))
        head, _, tail = dotted.partition(".")
        for scope in _function_scopes(node):
            bindings = _scope_bindings(scope)
            if head in bindings:
                class_name = bindings[head]
                if tail or class_name is None:
                    return None
                return self.qualify(class_name, file)
        qualified = self.qualify(dotted, file)
        return None if qualified is None else self._object_class(qualified, file, set())

    def qualify(self, dotted: str, file: Path) -> str | None:
        """Qualified name of a module-level dotted name in *file*: ``fastapi.FastAPI``."""
        head, _, tail = dotted.partition(".")
        if head in self._module_bindings(file):
            base: str | None = f"{_module_name(file)}.{head}"
        else:
            base = self._imported_names(file).get(head)
        if base is None:
            return None
        return f"{base}.{tail}" if tail else base

    def inherits_from(self, qualified: str, targets: frozenset[str], anchor: Path) -> bool:
        """Whether class *qualified* is one of *targets* or inherits from one of them.

        *anchor* is any file of the project, used to locate project modules.
        """
        return self._inherits(qualified, targets, anchor.resolve(), set())

    def module_file(self, module: str, anchor: Path) -> Path | None:
        """Source file of project module *module* (``app.api``), or None if not in the project."""
        package = package_of(anchor)
        root = anchor.parent
        for _ in package.split(".") if package else ():
            root = root.parent
        base = root.joinpath(*module.split("."))
        candidates = (base.parent / f"{base.name}.py", base / "__init__.py")
        for candidate in candidates:
            path = candidate.resolve()
            if self._trees.get(path) is not None or path.is_file():
                return path
        return None

    def _object_class(self, qualified: str, anchor: Path, seen: set[str]) -> str | None:
        """Class of the module-level object *qualified* (``app.api.router``)."""
        if qualified in seen:
            return None
        seen.add(qualified)
        found = self._find(qualified, anchor)
        if found is None:
            return None
        file, name = found
        bindings = self._module_bindings(file)
        if name in bindings:
            class_name = bindings[name]
            return None if class_name is None else self.qualify(class_name, file)
        imported = self._imported_names(file).get(name)
        return None if imported is None else self._object_class(imported, file, seen)

    def _inherits(
        self, qualified: str, targets: frozenset[str], anchor: Path, seen: set[str]
    ) -> bool:
        if qualified in targets:
            return True
        if qualified in seen:
            return False
        seen.add(qualified)
        found = self._find(qualified, anchor)
        if found is None:
            return False
        file, name = found
        tree = self._tree(file)
        classdef = None if tree is None else _module_class(tree, name)
        if classdef is None:
            imported = self._imported_names(file).get(name)
            return imported is not None and self._inherits(imported, targets, file, seen)
        bases = (self.qualify(base, file) for base in _bases(classdef))
        return any(base is not None and self._inherits(base, targets, file, seen) for base in bases)

    def _find(self, qualified: str, anchor: Path) -> tuple[Path, str] | None:
        """Split ``pkg.module.name`` into the project file of ``pkg.module`` and ``name``."""
        module, _, name = qualified.rpartition(".")
        if not module:
            return None
        file = self.module_file(module, anchor)
        return None if file is None else (file, name)

    def _set_tree(self, file: Path, tree: Module) -> None:
        if self._trees.get(file) is not tree:
            self._trees[file] = tree
            self._bindings.pop(file, None)
            self._imports.pop(file, None)

    def _tree(self, file: Path) -> Module | None:
        if file not in self._trees:
            try:
                source = file.read_text()
            except (OSError, UnicodeDecodeError):
                self._trees[file] = None
            else:
                self._trees[file] = parso.parse(source)
        return self._trees[file]

    def _module_bindings(self, file: Path) -> Bindings:
        if file not in self._bindings:
            tree = self._tree(file)
            self._bindings[file] = {} if tree is None else _scope_bindings(tree)
        return self._bindings[file]

    def _imported_names(self, file: Path) -> dict[str, str]:
        if file not in self._imports:
            tree = self._tree(file)
            self._imports[file] = {} if tree is None else imported_names(tree, package_of(file))
        return self._imports[file]


def _scope_bindings(scope: BaseNode) -> Bindings:
    """Names bound directly in a module or function, with their class if known.

    The last binding of a name wins.
    """
    bindings: Bindings = {}
    if isinstance(scope, Function):
        bindings.update(_parameter_bindings(scope))
    for node in _scope_nodes(scope):
        if node.type in {"classdef", "funcdef"}:
            bindings[node.children[1].value] = None
        elif node.type == "expr_stmt":
            bindings.update(_statement_bindings(node))
    return bindings


def _statement_bindings(stmt: BaseNode) -> Bindings:
    """Bindings of ``x = Class()``, ``a = b = Class()`` and ``x: Class [= ...]``."""
    target, operator = stmt.children[0], stmt.children[1]
    if operator.type == "annassign":
        if not isinstance(target, Name):
            return {}
        return {target.value: _expression_name(operator.children[1])}
    if not isinstance(operator, Leaf) or operator.value != "=":
        return {}
    class_name = _called_class(stmt.children[-1])
    targets = stmt.children[:-1:2]
    return {name.value: class_name for name in targets if isinstance(name, Name)}


def _parameter_bindings(funcdef: Function) -> Bindings:
    """Annotated parameters of a function: ``def register(app: FastAPI)``."""
    bindings: Bindings = {}
    for param in funcdef.get_params():
        annotation = param.annotation
        bindings[param.name.value] = None if annotation is None else _expression_name(annotation)
    return bindings


def _function_scopes(node: BaseNode | Leaf) -> Iterator[BaseNode]:
    """Enclosing functions of a node, innermost first (class bodies are not scopes for them)."""
    parent = node.parent
    while parent is not None:
        if parent.type == "funcdef":
            yield parent
        parent = parent.parent


def _module_class(tree: Module, name: str) -> BaseNode | None:
    """The last module-level ``class name`` definition."""
    found = None
    for node in _scope_nodes(tree):
        if node.type == "classdef" and node.children[1].value == name:
            found = node
    return found


def _scope_nodes(scope: BaseNode) -> Iterator[BaseNode]:
    """Yield statements of a scope, including nested blocks but not nested scopes."""
    for child in scope.children:
        if not isinstance(child, BaseNode):
            continue
        yield child
        if child.type not in SCOPES:
            yield from _scope_nodes(child)


def _bases(classdef: BaseNode) -> list[str]:
    """Dotted names of the base classes (keyword arguments like ``metaclass=`` skipped)."""
    children = classdef.children
    if children[2].type != "operator" or children[2].value != "(":
        return []
    arguments = children[3]
    nodes = arguments.children[::2] if arguments.type == "arglist" else [arguments]
    names = (_expression_name(node) for node in nodes)
    return [name for name in names if name is not None]


def _expression_name(node: BaseNode | Leaf) -> str | None:
    """Dotted name of an expression: ``FastAPI``, ``fastapi.APIRouter``, else None."""
    if isinstance(node, Leaf):
        return node.value if isinstance(node, Name) else None
    if node.type not in {"atom_expr", "power"}:
        return None
    return dotted_name(node.children)


def _called_class(node: BaseNode | Leaf) -> str | None:
    """``Class(...)`` / ``mod.Class(...)`` -> the callee's dotted name, else None."""
    if not isinstance(node, BaseNode) or node.type not in {"atom_expr", "power"}:
        return None
    call = node.children[-1]
    if not isinstance(call, BaseNode) or call.type != "trailer":
        return None
    opening = call.children[0]
    if not isinstance(opening, Leaf) or opening.value != "(":
        return None
    return dotted_name(node.children[:-1])


def dotted_name(nodes: Sequence[BaseNode | Leaf]) -> str | None:
    """``[a, .b, .c]`` (a name, then attribute trailers) -> ``"a.b.c"``, else None."""
    if not nodes or not isinstance(nodes[0], Name):
        return None
    parts: list[str] = [nodes[0].value]
    for trailer in nodes[1:]:
        attribute = _attribute(trailer)
        if attribute is None:
            return None
        parts.append(attribute)
    return ".".join(parts)


def _attribute(node: BaseNode | Leaf) -> str | None:
    """Return ``x`` for a ``.x`` trailer, None for other trailers (calls, subscripts)."""
    # Every child of an atom_expr after the first one is a trailer.
    assert isinstance(node, BaseNode)
    dot, name = node.children[0], node.children[-1]
    if isinstance(dot, Leaf) and dot.value == "." and isinstance(name, Name):
        return str(name.value)
    return None


def _root(node: BaseNode | Leaf) -> Module:
    while node.parent is not None:
        node = node.parent
    assert isinstance(node, Module)
    return node


def _module_name(file: Path) -> str:
    """Dotted module name of a project file: ``app/api/__init__.py`` -> ``app.api``."""
    package = package_of(file)
    if file.stem == "__init__":
        return package
    return f"{package}.{file.stem}" if package else file.stem
