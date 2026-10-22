# Plugins

Core operators know nothing about libraries. Some libraries wrap your types in
their own generics and read them at runtime, which changes what a mutation
means. Plugins teach typemut these rules. They are opt-in:

```toml
[typemut]
plugins = ["sqlalchemy", "fastapi"]
```

An unknown plugin name is logged as a warning and skipped. A plugin can claim an annotation and decide
its mutations (usually by running the core operators on a wrapped type and
dropping mutations that are invalid for the library), and can contribute its own
operators. Annotations no plugin claims are mutated as usual, minus the single
mutations a plugin drops as invalid for its library (`[typemut.ignore-types]` and
`[typemut.ignore-classes]` still apply to them).

## Third-party plugins

A package can ship its own plugin: subclass `typemut.plugins.base.Plugin` and
register it under the `typemut.plugins` entry point group. The entry point name
is the name used in `plugins = [...]`:

```toml
# pyproject.toml of the plugin package
[project.entry-points."typemut.plugins"]
django = "typemut_django:DjangoPlugin"
```

An entry point that fails to import or does not name a `Plugin` subclass is
logged as a warning and skipped.

A plugin's `find_mutations` receives the enabled operators and the class
registry. Its `drops(mutation, annotation)` can reject single core mutations of
annotations no plugin claimed, and `scan(files)` reads the project's files before
any annotation is mutated (for rules that depend on code elsewhere in the project). The `Plugin` base class also provides parso helpers
(`_node_code`, `_trailer_target`) that a plugin can use or override. Operators
a plugin returns from `operators()` subclass `TypeMutationOperator`, which
provides `_node_code`, `_is_qualified_name`, `_union_members` and `_type_params`.
The data types plugins and operators work with (`AnnotationNode`,
`AnnotationContext`, `Mutation`) live in `typemut.model`.
A plugin operator's `config_key` can be used in `[typemut.operators]` and
`[typemut.ignore-types]` like a built-in operator key. Keys that no available
operator has are reported as a warning and have no effect.

## sqlalchemy

For SQLAlchemy 2.0 declarative models (`Mapped[...]`, also `orm.Mapped[...]`).
SQLAlchemy derives the column type, nullability and relationship target from
the type inside `Mapped[...]`, so the plugin mutates that type instead of the
whole annotation:

| Annotation | Without plugin | With plugin |
|------------|----------------|-------------|
| `id: Mapped[int]` | `Mapped[int] \| None` (meaningless) | `Mapped[int \| None]` (nullable column) |
| `email: Mapped[str \| None]` | not mutated | `Mapped[str]` |
| `user: Mapped["UserDB"] = relationship()` | `Mapped["UserDB"] \| None` | `Mapped["UserDB \| None"]` |
| `profile: Mapped["ProfileDB \| None"] = relationship()` | `Mapped["ProfileDB \| None"] \| None` | `Mapped["ProfileDB"]` |
| `roles: Mapped[list[RoleDB]] = relationship()` | `Mapped[Sequence[RoleDB]]` | skipped |
| `payload: Mapped[dict[str, Any]]` | `Mapped[Mapping[str, Any]]` | skipped |
| `user: Mapped[UserDB] = relationship()` (`UserDB(BaseDB)`) | `Mapped[BaseDB]` | skipped |

Rules:

- Quoted forward references (`Mapped["UserDB | None"]`) are mutated inside the quotes.
- `WidenContainerType` skips the top-level type inside `Mapped[...]`: SQLAlchemy needs a
  concrete column type / collection class there (`list`, `set`), not an ABC. Nested
  containers (`Mapped[dict[str, list[int]]]`) are still widened.
- On relationship attributes (`= relationship(...)`):
  - `WidenType` is skipped: the target must be a mapped class, and widening usually points
    at the declarative base;
  - `AddOptional` is skipped for collections (`Mapped[list[X]]`): a collection
    relationship is an empty collection, never `None`.
- `WriteOnlyMapped[...]` and `DynamicMapped[...]` get no mutations: they are always
  relationship collections, and none of the core mutations is valid for them.

Nullability mismatches between `Mapped[X | None]` and `mapped_column(nullable=...)`
are a runtime/schema issue, not a typing one, so the plugin does not generate them.

## fastapi

FastAPI calls route handlers itself, and tests reach them over HTTP, so no Python
code calls them. The type checker has no caller to check a mutated signature
against: `-> RedirectResponse` → `-> RedirectResponse | None` always survives.
The plugin skips all parameter and return annotations of such functions:

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/login")
async def login(next: str | None = None) -> RedirectResponse:  # not mutated
    target: str | None = next  # still mutated
    ...
```

A function counts as an endpoint when it is decorated with
`@<receiver>.<method>(...)`, where `<method>` is a route method (`get`, `post`, `put`,
`patch`, `delete`, `head`, `options`, `trace`, `api_route`, `websocket`) or
`exception_handler`, `middleware`, `on_event`. The receiver has to be an instance
of `fastapi.FastAPI` / `fastapi.APIRouter`, or of a project class inheriting from
them (also across modules). The type is resolved statically from imports, not
from variable names:

- `app = FastAPI()`, `router: APIRouter = make_router()`, `def register(app: FastAPI)`;
- `app = FastAPI()` inside an app factory function;
- a receiver imported from another project module, including re-exports
  (`from app.api import router`, `from app import api` + `@api.router.get`).

Unresolvable receivers (a factory call without annotation, `self.router`, a star
import) are not treated as endpoints. The same goes for functions registered
without a decorator (`app.add_api_route(...)`) or used only through `Depends(...)`.
Mark those with `# pragma: no mutate`.

## pydantic

For pydantic 2 models: classes inheriting from `pydantic.BaseModel`, `RootModel` or
`pydantic_settings.BaseSettings` (directly or through project classes, also across
modules) and `@pydantic.dataclasses.dataclass` classes. Pydantic reads field
annotations when it creates the class, so some mutations that pass the type checker
break the model at import time or make it unusable. The plugin drops them from
model fields:

| Field | Mutation | Why it is dropped |
|-------|----------|-------------------|
| `item: Item` | `Item` → `BaseModel` | a `BaseModel` field fails to validate input (`'BaseModel' object has no attribute '__private_attributes__'`) and dumps as `{}`; same for `RootModel` / `BaseSettings` |
| `pet: Cat \| Dog = Field(discriminator="pet_type")` | `Cat` → `Pet` | the base has no discriminator field (`discriminator-no-field`) |
| `pet_type: Literal["cat"]` (a discriminator) | `Literal["cat"] \| None` | `PydanticUserError: discriminator-needs-literal` |
| `ids: Sequence[int]` | `Collection[int]` | no pydantic schema (`PydanticSchemaGenerationError`); same for `Iterator`, `Container`, `Sized`, `Reversible`, `KeysView`, `ValuesView`, `AsyncIterable`, `AsyncIterator`, `AsyncGenerator` |

A `Literal` field counts as a discriminator when its name is used as
`discriminator="..."` or `Discriminator("...")` anywhere in the project. Other
mutations of fields stay: widening to a project base model, `X | None`,
`list` → `Sequence` and removing `Literal` / union members are valid for pydantic
and change behaviour that tests can catch. Outside model fields nothing is dropped.

Like `fastapi`, the plugin also skips the parameter and return annotations of
functions only pydantic calls:

- methods decorated with `@field_validator`, `@model_validator`, `@field_serializer`,
  `@model_serializer` (and the deprecated `@validator`, `@root_validator`);
- module-level functions passed to `AfterValidator`, `BeforeValidator`,
  `PlainValidator`, `WrapValidator`, `PlainSerializer` or `WrapSerializer` in the same
  module (`Annotated[int, AfterValidator(is_even)]`);
- `__get_pydantic_core_schema__`, `__get_pydantic_json_schema__` and `model_post_init`
  methods.

`@computed_field` properties are mutated as usual: Python code reads them.

## Other frameworks: `[typemut.entrypoints]`

Other frameworks register handlers the same way: in-house RPC layers, message
consumers, task queues. Name them in `[typemut.entrypoints]` to skip the
parameter and return annotations of their handlers, without a plugin per
framework (no entry in `plugins` needed):

```toml
[typemut.entrypoints]
# functions decorated with one of these
decorators = ["mylib.rpc.*.method", "faststream.*.subscriber", "taskiq.*.task"]
# methods of classes inheriting from one of these
base-classes = ["mylib.rpc.Endpoint"]
# functions with a parameter whose annotation references one of these (DI markers)
parameter-types = ["mylib.rpc.*.Dependency", "dishka.FromDishka"]
```

```python
from mylib.rpc import Endpoint, Router

rpc = Router()


@rpc.method()  # mylib.rpc.Router.method
async def get_item(item_id: int, service: rpc.Dependency[ItemService]) -> ItemSchema:  # not mutated
    item: ItemSchema | None = await service.get(item_id)  # still mutated
    ...


class Items(Endpoint):
    async def get_item(self, item_id: int) -> ItemSchema: ...  # not mutated
```

Patterns are `fnmatch` globs (`*` matches dots too) against qualified names,
resolved statically like the `fastapi` plugin does (imports, aliases, relative
imports, re-exports and objects imported from other project modules):

- **decorators**: `@x`, `@x.y` or `@x.y(...)`. The decorator matches as the
  qualified name of what it refers to (`from taskiq import task` → `taskiq.task`),
  and, when its receiver is an instance (`rpc = Router()`, `rpc: Router = make()`,
  `def register(rpc: Router)`), as `<class>.<attribute>` for the instance's class
  and each of its base classes: `@rpc.method()` → `mylib.rpc.Router.method`, also
  with `rpc = AppRouter()` where `class AppRouter(Router)` is a project class.
  Classes are named as they are imported (`from mylib.rpc import Router` →
  `mylib.rpc.Router`), not where they are defined.
- **base-classes**: methods (not nested functions) of a class whose bases
  inherit from a matching class, directly or through project classes in other
  modules. Methods of the matching class itself are mutated.
- **parameter-types**: every name the annotation references counts
  (`Dependency[Service]`, `Annotated[Service, Inject]`), resolved like decorators:
  `rpc.Dependency` with `rpc = Router()` is `mylib.rpc.Router.Dependency`.
  String annotations and default values (`= Depends(...)`) are not looked at.
- Unresolvable names (factory calls, `self.router`, star imports) don't match.
- Unknown keys and invalid values are logged as warnings and skipped.
