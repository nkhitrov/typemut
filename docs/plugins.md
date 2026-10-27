# Plugins

Core operators know nothing about libraries. Some libraries wrap your types in
their own generics and read them at runtime, which changes what a mutation
means. Plugins teach typemut these rules. They are opt-in:

```toml
[typemut]
plugins = ["sqlalchemy", "fastapi", "faststream", "dmr"]
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
registry. A plugin that needs project-wide facts overrides `scan(files)`: it is
called once with every source file before any `find_mutations`. Its `drops(mutation, annotation)`
can reject single core mutations of annotations no plugin claimed. The `Plugin` base class also provides parso helpers
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
of `fastapi.FastAPI` / `fastapi.APIRouter`, of a known third-party subclass
(FastStream's FastAPI routers: `faststream.kafka.fastapi.KafkaRouter`, `RabbitRouter`,
`NatsRouter`, `RedisRouter`, ..., also from `faststream_fastapi`), or of a project
class inheriting from them (also across modules). Library sources are not parsed,
so other third-party subclasses are not recognised. The type is resolved statically
from imports, not from variable names:

- `app = FastAPI()`, `router: APIRouter = make_router()`, `def register(app: FastAPI)`;
- `app = FastAPI()` inside an app factory function;
- a receiver imported from another project module, including re-exports
  (`from app.api import router`, `from app import api` + `@api.router.get`).

Skipping endpoints also keeps out mutants FastAPI rejects at import:
`-> HTMLResponse` → `-> HTMLResponse | None` on an endpoint raises
`FastAPIError: Invalid args for response field`. The same mutation on a dependency
or a helper function is valid.

**Dependency providers.** `Annotated[User, Depends(get_user)]` does not relate
`User` to the return type of `get_user`, so a mutated return type of a dependency
survives whenever nothing but FastAPI calls it. The plugin skips the **return
annotation** of such providers:

```python
async def get_user(token: Annotated[str, Depends(oauth2_scheme)]) -> User:  # return not mutated
    ...

@app.get("/me")
async def me(user: Annotated[User, Depends(get_user)]) -> User: ...
```

A provider is what `Depends(...)` / `Security(...)` (from `fastapi`, `fastapi.params`
or `fastapi.param_functions`) refers to anywhere in the module path: in a default
value, inside `Annotated[...]`, in a type alias, in `dependencies=[...]` of a route,
router or app. Keys and values of `app.dependency_overrides[f] = g` are providers as
well. For a callable instance (`checker = Checker(...)`, `Depends(checker)`) it is
`Checker.__call__`. Names are resolved like endpoint receivers (imports, re-exports,
`deps.get_user`).

- Parameters of providers are still mutated: the provider's body and parameter
  defaults check them like in any function.
- A provider that the project also uses directly (`get_user(token)`,
  `get_settings.cache_clear()`, `checker("q")`) is mutated as usual: the type checker
  has a caller to check it against. Only files in the module path (minus
  `excluded-modules`) are searched for such uses; a direct call from tests outside
  it is not seen.
- `Depends()` without an argument (the annotated class is the dependency), lambdas,
  methods and nested functions are not treated as providers.

Unresolvable receivers (a factory call without annotation, `self.router`, a star
import) are not treated as endpoints. The same goes for functions registered
without a decorator (`app.add_api_route(...)`). Mark those with `# pragma: no mutate`.

## faststream

FastStream calls message handlers itself: it decodes the message body into the
handler's parameters and publishes its return value. Tests reach handlers by
publishing messages, so no Python code calls them: `-> str` → `-> str | None`
always survives. Mutating a handler's parameters breaks the application rather
than its typing: `msg: User` → `msg: BaseModel` passes the type checker, but
FastStream can no longer decode the message, and `logger: Logger` →
`logger: Logger | None` turns an injected object into a body field. The plugin
skips all parameter and return annotations of such functions:

```python
from faststream import FastStream
from faststream.kafka import KafkaBroker

broker = KafkaBroker("localhost:9092")
app = FastStream(broker)


@broker.subscriber("in-topic")
@broker.publisher("out-topic")
async def handle(data: User, logger: Logger) -> str:  # not mutated
    reply: str | None = None  # still mutated
    ...


@app.on_startup
async def setup(context: ContextRepo) -> None: ...  # not mutated


async def custom_parser(msg: ConsumerRecord, original: ParserFn) -> KafkaMessage: ...  # not mutated


rabbit = RabbitBroker(parser=custom_parser)
```

A function is skipped when it is:

- decorated with `@<receiver>.subscriber(...)` or `@<receiver>.publisher(...)`, or
  registered with `<receiver>.subscriber(...)(handler)`, where the receiver is a
  broker or router (`KafkaBroker`, `RabbitBroker`, `RedisBroker`, `NatsBroker`,
  `faststream.confluent.KafkaBroker`, `KafkaRouter`, ..., the FastAPI integration
  routers `faststream.kafka.fastapi.KafkaRouter`, ... and `faststream_fastapi.*Router`);
- a lifespan hook: `@app.on_startup`, `after_startup`, `on_shutdown`, `after_shutdown`
  of a `FastStream` / `AsgiFastStream` instance, `@router.after_startup` /
  `on_broker_shutdown` of a FastAPI integration router;
- passed by name, in the same module, as `parser=`, `decoder=`, `middlewares=`
  (also inside a tuple or list), `lifespan=`, `on_startup=`-style hooks or `call=`
  to a broker, router, application, subscriber or publisher, as the handler of a
  route (`KafkaRoute(handle, "topic")`), or as a dependency provider
  (`Depends(get_user)`): the type checker does not relate
  `Annotated[User, Depends(get_user)]` to the return type of `get_user`.

Receivers and classes are resolved statically like in the `fastapi` plugin
(imports, aliases, project subclasses, objects imported from other project
modules). Methods of `BaseMiddleware` subclasses are mutated: the type checker
checks them against the overridden methods. Functions passed by attribute
(`parser=codec.parse`) or from another module are not recognised; mark those
with `# pragma: no mutate`.

Compared with `[typemut.entrypoints]` (`decorators = ["faststream.*.subscriber"]`),
the plugin also covers lifespan hooks, parsers, decoders, middlewares, routes,
`broker.subscriber(...)(handler)` and `Depends(...)` providers, and needs no
patterns: the list of FastStream classes is built in.

## dmr

For [django-modern-rest](https://github.com/wemake-services/django-modern-rest)
(`dmr`). dmr calls controller endpoints itself and reads their return
annotations when the controller class is created, to build response schemas
and validation. No Python code calls an endpoint, so `-> UserModel` →
`-> UserModel | None` always survives; on a streaming endpoint
(`-> AsyncIterator[X] | None`) or next to explicit `responses=` such a mutant
even breaks the controller at import time. The plugin skips the return
annotations of endpoints:

```python
from dmr import Body, Controller, ResponseSpec, modify, validate
from dmr.plugins.pydantic import PydanticSerializer


class UserController(Controller[PydanticSerializer]):
    request: AuthenticatedHttpRequest[User]  # still mutated

    @modify(status_code=HTTPStatus.OK)
    def post(self, parsed_body: Body[UserModel]) -> UserModel:  # return not mutated
        return parsed_body

    @validate(ResponseSpec(UserModel, status_code=HTTPStatus.OK))
    def put(self, parsed_body: Body[UserModel]) -> HttpResponse:  # still mutated
        ...

    def to_error(self, raw_data: Any, **kwargs: Any) -> HttpResponse:  # still mutated
        ...
```

An endpoint is:

- a method named after an HTTP method (`get`, `post`, `put`, `patch`, `delete`,
  `head`, `trace`, `connect`, and `meta` for OPTIONS) of a class inheriting
  from `dmr.Controller` or a dmr streaming controller (`SSEController`,
  `JsonLinesController`), directly or through project classes in any module;
  generic bases (`Controller[PydanticSerializer]`) count;
- any function decorated with `@modify` / `@modify.lazy` (`dmr.modify`,
  `dmr.streaming.modify`, or a project instance like
  `modify: Final = ModifyEndpoint(MyExtras)`).

Mutated as usual:

- the return annotation of an endpoint decorated with `@validate` /
  `@validate.lazy` (the same forms as `@modify`): `validate` binds the return type to `HttpResponse`, so
  mypy kills these mutants;
- endpoint parameters (`parsed_body: Body[UserModel]`): the endpoint body uses
  them, and mypy kills most of their mutants there;
- other methods and attributes of controllers (`to_error`, `handle_*_error`,
  `request: ...`): they override `Controller` API and are checked against it;
- methods of dmr's ready-made controllers (JWT, token and session views)
  overridden in a subclass: they are checked against the method they override.

Fields of the models dmr serializes (`Body[...]`, `Query[...]`, `Headers[...]`,
endpoint returns) are not touched: mypy kills field mutants wherever Python code
constructs or reads the model. To skip them anyway, list the model base classes
in [`[typemut.ignore-classes]`](filtering.md) (`msgspec.Struct`,
`pydantic.BaseModel`, `typing.TypedDict`); models defined with a decorator
(`@dataclass`, `@attrs.define`) need `# pragma: no mutate`.

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
  modules. Generic bases count without their type arguments
  (`class Items(Endpoint[ItemSchema])` matches `mylib.rpc.Endpoint`). Methods of
  the matching class itself are mutated.
- **parameter-types**: every name the annotation references counts
  (`Dependency[Service]`, `Annotated[Service, Inject]`), resolved like decorators:
  `rpc.Dependency` with `rpc = Router()` is `mylib.rpc.Router.Dependency`.
  String annotations and default values (`= Depends(...)`) are not looked at.
- Unresolvable names (factory calls, `self.router`, star imports) don't match.
- Unknown keys and invalid values are logged as warnings and skipped.
