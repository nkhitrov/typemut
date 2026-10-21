"""Pydantic 2 plugin: drop mutations pydantic rejects at runtime, skip functions it calls.

Pydantic reads the annotations of model fields when it creates the class, so
some mutations that type-check are invalid for it. In fields of models
(classes inheriting from ``pydantic.BaseModel`` / ``RootModel`` /
``pydantic_settings.BaseSettings``, directly or through project classes, and
``@pydantic.dataclasses.dataclass`` classes) the plugin drops:

- widening to pydantic's own base classes (``Item`` -> ``BaseModel``): a
  ``BaseModel`` field cannot validate input (``'BaseModel' object has no
  attribute '__private_attributes__'``) and dumps as ``{}``;
- widening a member of a discriminated union (a field defined with
  ``discriminator=``) to its base class: the base has no discriminator field
  (``PydanticUserError: discriminator-no-field``);
- ``X | None`` on a ``Literal[...]`` field used as a discriminator
  (``Field(discriminator="pet_type")`` / ``Discriminator("pet_type")``
  anywhere in the project): the field must be a plain ``Literal``
  (``PydanticUserError: discriminator-needs-literal``);
- mutations to container ABCs pydantic has no schema for (``Sequence[int]``
  -> ``Collection[int]``, ``Generator`` -> ``Iterator``):
  ``PydanticSchemaGenerationError``.

Like the ``fastapi`` plugin, it also skips the signatures of functions only
pydantic calls: ``@field_validator`` / ``@model_validator`` /
``@field_serializer`` / ``@model_serializer`` (and the deprecated
``@validator`` / ``@root_validator``) methods, module-level functions passed
to ``AfterValidator(...)`` and the other ``Annotated`` validators and
serializers of their module, and ``__get_pydantic_core_schema__`` /
``__get_pydantic_json_schema__`` / ``model_post_init`` methods.
``@computed_field`` properties are mutated as usual: Python code reads them.

Names are resolved statically (see ``typemut.symbols``), never by variable
names. Discriminators are matched by field name: a ``Literal`` field named
like a discriminator of any union in the project keeps its ``| None``.
"""

from __future__ import annotations

import ast
from collections.abc import Container, Iterable
from pathlib import Path

import parso
from parso.python.tree import BaseNode, Class, ClassOrFunc, Function, Leaf, Module, Name

from typemut.hierarchy import ClassNames
from typemut.imports import ImportInjector, ModuleImports
from typemut.model import AnnotationContext, AnnotationNode, Mutation
from typemut.plugins.base import HandlerPlugin
from typemut.symbols import ScopeReader, SymbolResolver

# Pydantic's own model base classes, under every name pydantic exports them.
MODEL_BASES = frozenset(
    (
        "pydantic.BaseModel",
        "pydantic.main.BaseModel",
        "pydantic.RootModel",
        "pydantic.root_model.RootModel",
        "pydantic_settings.BaseSettings",
        "pydantic_settings.main.BaseSettings",
    )
)

DATACLASS_DECORATORS = frozenset(("pydantic.dataclasses.dataclass",))

# Decorators of methods that pydantic calls during validation and serialization.
VALIDATOR_DECORATORS = frozenset(
    (
        *(
            f"{module}.{name}"
            for module in ("pydantic", "pydantic.functional_validators")
            for name in ("field_validator", "model_validator")
        ),
        *(
            f"{module}.{name}"
            for module in ("pydantic", "pydantic.functional_serializers")
            for name in ("field_serializer", "model_serializer")
        ),
        *(
            f"{module}.{name}"
            for module in ("pydantic", "pydantic.deprecated.class_validators")
            for name in ("validator", "root_validator")
        ),
    )
)

# ``Annotated`` metadata whose first argument is a function pydantic calls.
ANNOTATED_FUNCTIONS = frozenset(
    (
        *(
            f"{module}.{name}"
            for module in ("pydantic", "pydantic.functional_validators")
            for name in ("AfterValidator", "BeforeValidator", "PlainValidator", "WrapValidator")
        ),
        *(
            f"{module}.{name}"
            for module in ("pydantic", "pydantic.functional_serializers")
            for name in ("PlainSerializer", "WrapSerializer")
        ),
    )
)

# Methods pydantic calls on custom types and models.
HOOK_METHODS = frozenset(
    ("__get_pydantic_core_schema__", "__get_pydantic_json_schema__", "model_post_init")
)

# Container ABCs that pydantic 2 cannot build a schema for in a field.
NO_SCHEMA = frozenset(
    (
        "Collection",
        "Container",
        "Iterator",
        "Reversible",
        "Sized",
        "KeysView",
        "ValuesView",
        "AsyncIterable",
        "AsyncIterator",
        "AsyncGenerator",
    )
)

DISCRIMINATOR_KEYWORD = "discriminator"
DISCRIMINATOR_CLASS = "Discriminator"
LITERAL = "Literal"

# id(module tree) -> (module tree, names of the functions its Annotated metadata calls)
_FunctionsCache = dict[int, tuple[Module, frozenset[str]]]

# parso's children are untyped, so narrower node types in the signatures below
# (BaseNode or Leaf alone) pass the type checker too; they are marked no mutate.


class PydanticPlugin(HandlerPlugin):
    name = "pydantic"

    def __init__(
        self,
        resolver: SymbolResolver | None = None,
        scopes: ScopeReader | None = None,
        classes: ClassNames | None = None,
        imports: ModuleImports | None = None,
        calls: CallArguments | None = None,
    ) -> None:
        super().__init__(resolver, scopes)
        self._classes = classes or ClassNames()
        self._imports = imports or ModuleImports()
        self._calls = calls or CallArguments()
        self._discriminators: set[str] = set()
        self._functions: _FunctionsCache = {}

    def scan(self, files: Iterable[Path]) -> None:
        """Collect the discriminator field names used anywhere in *files*."""
        for file in files:
            try:
                source = file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            self._discriminators.update(self._discriminator_names(parso.parse(source)))

    def drops(self, mutation: Mutation, annotation: AnnotationNode) -> bool:
        field = self._model_field(annotation)
        if field is None:
            return False
        introduced = ImportInjector.type_name(mutation.mutated)
        if introduced in NO_SCHEMA and introduced != ImportInjector.type_name(mutation.original):
            return True
        if mutation.operator == "WidenType":
            # A member of a discriminated union, or pydantic's own base class.
            return DISCRIMINATOR_KEYWORD in self._calls.keywords(field) or (
                self._introduced_class(mutation, annotation.file) in MODEL_BASES
            )
        if mutation.operator == "AddOptional":
            # A Literal discriminator.
            return (
                LITERAL in self._names(annotation.node)
                and field.children[0].value in self._discriminators
            )
        return False

    def _is_handler(self, funcdef: Function, file: Path) -> bool:
        if self._decorated_with(funcdef, VALIDATOR_DECORATORS, file):
            return True
        scope = funcdef.search_ancestor("classdef", "funcdef")
        if scope is not None:
            return scope.type == "classdef" and funcdef.name.value in HOOK_METHODS
        return funcdef.name.value in self._annotated_functions(self._scopes.root(funcdef), file)

    def _decorated_with(
        self, node: ClassOrFunc, names: Container[str], file: Path
    ) -> bool:  # pragma: no mutate (truth-tested)
        """Whether a decorator of *node* refers to one of *names* (``@x``, ``@x(...)``)."""
        references = (self._decorator_reference(decorator) for decorator in self._decorators(node))
        return any(
            reference is not None and self._resolver.qualify(reference.name, file) in names
            for reference in references
        )

    def _model_field(self, annotation: AnnotationNode) -> BaseNode | None:
        """The ``name: annotation [= default]`` statement of a model field, else None."""
        annassign = annotation.node.parent
        if annotation.context != AnnotationContext.VARIABLE or annassign is None:
            return None
        statement = annassign.parent
        classdef = self._classes.enclosing_class(annotation.node)
        if (
            annassign.type != "annassign"
            or statement is None
            or not isinstance(statement.children[0], Name)
            or classdef is None
            or not self._is_model(classdef, annotation.file)
        ):
            return None
        return statement

    def _is_model(self, classdef: Class, file: Path) -> bool:  # pragma: no mutate (truth-tested)
        """Whether *classdef* is a pydantic model or a pydantic dataclass."""
        bases = self._classes.bases(classdef, file)
        return any(
            self._resolver.inherits_from(base, MODEL_BASES, file) for base in bases
        ) or self._decorated_with(classdef, DATACLASS_DECORATORS, file)

    def _introduced_class(self, mutation: Mutation, file: Path) -> str | None:
        """Qualified name of the class a WidenType mutation widens to."""
        imported = (
            {}
            if mutation.required_import is None
            else self._imports.names(parso.parse(mutation.required_import))
        )
        return imported.get(mutation.mutated) or self._resolver.qualify(mutation.mutated, file)

    def _annotated_functions(self, tree: Module, file: Path) -> Container[str]:
        """Names of the functions passed to ``AfterValidator(...)`` & co. in a module."""
        cached = self._functions.get(id(tree))
        if cached is None or cached[0] is not tree:
            names = frozenset(self._passed_functions(tree, file))
            cached = (tree, names)
            self._functions[id(tree)] = cached
        return cached[1]

    def _passed_functions(
        self,
        node: BaseNode | Leaf,  # pragma: no mutate
        file: Path,
    ) -> Iterable[str]:
        if isinstance(node, Leaf):
            return
        call = self._call(node)
        if call is not None and self._resolver.qualify(call[0], file) in ANNOTATED_FUNCTIONS:
            function = self._calls.first_argument(call[1])
            if isinstance(function, Name):
                yield function.value
        for child in node.children:
            yield from self._passed_functions(child, file)

    def _discriminator_names(self, node: BaseNode | Leaf) -> Iterable[str]:  # pragma: no mutate
        """Field names given as ``discriminator="name"`` or ``Discriminator("name")``."""
        if isinstance(node, Leaf):
            return
        value: BaseNode | Leaf | None = None
        if self._calls.keyword(node) == DISCRIMINATOR_KEYWORD:
            value = node.children[-1]
        call = self._call(node)
        if call is not None and call[0].rpartition(".")[2] == DISCRIMINATOR_CLASS:
            value = self._calls.first_argument(call[1])
        name = self._calls.string(value)
        if name is not None:
            yield name
        for child in node.children:
            yield from self._discriminator_names(child)

    def _call(self, node: BaseNode) -> tuple[str, BaseNode] | None:
        """``(dotted callee, call trailer)`` for ``name(...)`` / ``a.name(...)``, else None."""
        if self._trailer_target(node, "(") is None:
            return None
        callee = self._scopes.dotted_name(node.children[:-1])
        trailer = node.children[-1]
        assert isinstance(trailer, BaseNode)
        return None if callee is None else (callee, trailer)

    def _names(self, node: BaseNode | Leaf) -> Iterable[str]:
        """Every name in a subtree."""
        if isinstance(node, Name):
            yield node.value
        elif isinstance(node, BaseNode):
            for child in node.children:
                yield from self._names(child)


class CallArguments:
    """Reads the arguments of calls in parso trees."""

    def first_argument(self, trailer: BaseNode) -> BaseNode | Leaf | None:  # pragma: no mutate
        """The first argument of a call trailer ``(a, ...)``; a keyword argument's value."""
        argument = trailer.children[1]
        if isinstance(argument, BaseNode) and argument.type == "arglist":
            argument = argument.children[0]
        if isinstance(argument, Leaf) and argument.type == "operator":
            # ``()``: no arguments.
            return None
        if self.keyword(argument) is not None:
            assert isinstance(argument, BaseNode)
            return argument.children[-1]
        return argument

    def keyword(self, node: BaseNode | Leaf) -> str | None:
        """``name`` for a keyword argument ``name=value``, else None."""
        if not isinstance(node, BaseNode) or node.type != "argument":
            return None
        keyword, operator = node.children[0], node.children[1]
        if isinstance(keyword, Name) and isinstance(operator, Leaf) and operator.value == "=":
            return str(keyword.value)
        return None

    def keywords(self, node: BaseNode | Leaf) -> Iterable[str]:  # pragma: no mutate
        """Names of every keyword argument in a subtree."""
        keyword = self.keyword(node)
        if keyword is not None:
            yield keyword
        if isinstance(node, BaseNode):
            for child in node.children:
                yield from self.keywords(child)

    def string(self, node: BaseNode | Leaf | None) -> str | None:
        """The value of a plain string literal, None for anything else."""
        if not isinstance(node, Leaf) or node.type != "string":
            return None
        value = ast.literal_eval(node.value)
        return value if isinstance(value, str) else None
