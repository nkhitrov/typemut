"""Tests for the FastAPI plugin."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.plugins.base import Plugin
from typemut.plugins.fastapi import FastAPIPlugin
from typemut.registry import Registry

ENDPOINT = "def endpoint(q: int | None) -> RedirectResponse: ...\n"

CORE_ENDPOINT_MUTATIONS = {
    ("RemoveOptional", "int | None", "int"),
    ("AddOptional", "RedirectResponse", "RedirectResponse | None"),
}


def mutations(file: Path, plugins: list[str]) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *file* (read from disk).

    Plugins scan every module in the directory of *file* and below first.
    """
    return find_mutations(file, PluginRegistry().get(plugins))


def find_mutations(file: Path, loaded: Collection[Plugin]) -> set[tuple[str, str, str]]:
    operators = OperatorRegistry().enabled({})
    files = sorted(file.parent.rglob("*.py"))
    for plugin in loaded:
        plugin.scan(files)
    return {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(file)
        for mutation in MutationFinder(operators, Registry(), loaded).find(annotation)
    }


def write_project(root: Path, files: dict[str, str]) -> None:
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\n{ENDPOINT}',
            id="app-get",
        ),
        pytest.param(
            f'import fastapi\nrouter = fastapi.APIRouter()\n@router.post("/")\n{ENDPOINT}',
            id="module-qualified-router",
        ),
        pytest.param(
            f'from fastapi import APIRouter as R\nr = R()\n@r.put("/")\n{ENDPOINT}',
            id="aliased-import",
        ),
        pytest.param(
            f'from fastapi.routing import APIRouter\nr = APIRouter()\n@r.delete("/")\n{ENDPOINT}',
            id="routing-module",
        ),
        pytest.param(
            f'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\nasync {ENDPOINT}',
            id="async-endpoint",
        ),
        pytest.param(
            f'from fastapi import FastAPI\napp = FastAPI()\n@app.websocket("/ws")\n{ENDPOINT}',
            id="websocket",
        ),
        pytest.param(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            f"@app.exception_handler(ValueError)\n{ENDPOINT}",
            id="exception-handler",
        ),
        pytest.param(
            "from fastapi import FastAPI\napp = FastAPI()\n"
            f'@cache\n@app.api_route("/", methods=["GET"])\n@other\n{ENDPOINT}',
            id="route-decorator-not-first",
        ),
        pytest.param(
            f'from fastapi import APIRouter\nrouter: APIRouter = make()  # pragma: no mutate\n@router.get("/")\n{ENDPOINT}',
            id="annotated-binding",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "def create_app() -> None:\n"
            "    app = FastAPI()\n"
            '    @app.get("/")\n'
            f"    {ENDPOINT}",
            id="app-factory",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "def register(app: FastAPI) -> None:\n"
            '    @app.get("/")\n'
            f"    {ENDPOINT}",
            id="annotated-parameter",
        ),
        pytest.param(
            "from fastapi import APIRouter\n"
            "class Base(APIRouter): ...\n"
            "class Router(Mixin, Base, metaclass=Meta): ...\n"
            "router = Router()\n"
            f'@router.get("/")\n{ENDPOINT}',
            id="subclass-in-module",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "def create_app() -> None:\n"
            "    app = FastAPI()\n"
            "    def register() -> None:\n"
            "        x = 1\n"
            '        @app.get("/")\n'
            f"        {ENDPOINT}",
            id="binding-in-outer-function",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "if True:\n"
            "    app = FastAPI()\n"
            f'@app.get("/")\n{ENDPOINT}',
            id="binding-in-block",
        ),
    ],
)
def test_endpoint_signature_is_skipped(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == set()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(ENDPOINT, id="undecorated"),
        pytest.param(f"@functools.cache\n{ENDPOINT}", id="non-call-decorator"),
        pytest.param(f'@get("/")\n{ENDPOINT}', id="bare-route-name"),
        pytest.param(
            f"from fastapi import FastAPI\napp = FastAPI()\n@app.get\n{ENDPOINT}",
            id="route-method-without-call",
        ),
        pytest.param(
            f'from fastapi import FastAPI\napp = FastAPI()\n@app.fetch("/")\n{ENDPOINT}',
            id="not-a-route-method",
        ),
        pytest.param(
            f'class FastAPI: ...\napp = FastAPI()\n@app.get("/")\n{ENDPOINT}',
            id="local-class-named-fastapi",
        ),
        pytest.param(
            f'from mylib import FastAPI\napp = FastAPI()\n@app.get("/")\n{ENDPOINT}',
            id="fastapi-name-from-other-package",
        ),
        pytest.param(
            f'from fastapi import FastAPI\n@FastAPI().get("/")\n{ENDPOINT}',
            id="receiver-not-a-name",
        ),
        pytest.param(
            f'import cachetools\ncache = cachetools.Cache()\n@cache.get("k")\n{ENDPOINT}',
            id="get-on-other-object",
        ),
        pytest.param(
            f'from fastapi import APIRouter\nrouter = get_router()\n@router.get("/")\n{ENDPOINT}',
            id="factory-call",
        ),
        pytest.param(
            f'from fastapi import FastAPI\napp = FastAPI\n@app.get("/")\n{ENDPOINT}',
            id="class-not-instance",
        ),
        pytest.param(
            f'from fastapi import FastAPI\n@undefined.get("/")\n{ENDPOINT}',
            id="unknown-receiver",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "class Views:\n"
            "    def __init__(self) -> None:\n"
            "        self.app = FastAPI()\n"
            "    def register(self) -> None:\n"
            '        @self.app.get("/")\n'
            f"        {ENDPOINT}",
            id="attribute-of-self",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "def create_app() -> None:\n"
            "    app = make()\n"
            '    @app.get("/")\n'
            f"    {ENDPOINT}",
            id="local-factory-call",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "def create_app() -> None:\n"
            "    app = FastAPI()\n"
            '    @app.router.get("/")\n'
            f"    {ENDPOINT}",
            id="local-attribute",
        ),
        pytest.param(
            f'import fastapi\n@fastapi.get("/")\n{ENDPOINT}',
            id="module-receiver",
        ),
        pytest.param(
            f'from fastapi import FastAPI\nrouters = [FastAPI()]\n@routers[0].get("/")\n{ENDPOINT}',
            id="subscript-receiver",
        ),
        pytest.param(
            f'import fastapi\napp = fastapi.applications\n@app.get("/")\n{ENDPOINT}',
            id="attribute-value",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "async def create_app() -> None:\n"
            "    app = await make()\n"
            '    @app.get("/")\n'
            f"    {ENDPOINT}",
            id="awaited-value",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "async def create_app() -> None:\n"
            "    app = await pending\n"
            '    @app.get("/")\n'
            f"    {ENDPOINT}",
            id="awaited-name",
        ),
        pytest.param(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "app.state: int = 1  # pragma: no mutate\n"
            "app.extra = FastAPI()\n"
            f'@app.extra.get("/")\n{ENDPOINT}',
            id="attribute-targets-are-not-bindings",
        ),
    ],
)
def test_other_functions_are_mutated(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    expected = mutations(tmp_path / "main.py", [])
    assert mutations(tmp_path / "main.py", ["fastapi"]) == expected
    assert CORE_ENDPOINT_MUTATIONS <= expected


def test_augmented_assignment_keeps_binding(tmp_path: Path) -> None:
    source = f'from fastapi import FastAPI\napp = FastAPI()\napp += 1\n@app.get("/")\n{ENDPOINT}'
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == set()


def test_body_annotations_are_mutated(tmp_path: Path) -> None:
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/")\n'
        "def endpoint() -> None:\n"
        "    x: int | None = None\n"
        "    def helper() -> RedirectResponse: ...\n"
    )
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == {
        ("RemoveOptional", "int | None", "int"),
        ("AddOptional", "RedirectResponse", "RedirectResponse | None"),
    }


def test_variable_annotations_are_mutated(tmp_path: Path) -> None:
    source = "from fastapi import FastAPI\napp: FastAPI | None = None\n"
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == {
        ("RemoveOptional", "FastAPI | None", "FastAPI"),
    }


PACKAGE = {"app/__init__.py": ""}


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            {
                "app/routers.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
                "app/views.py": f'from app.routers import router\n@router.get("/")\n{ENDPOINT}',
            },
            id="imported-router",
        ),
        pytest.param(
            {
                "app/routers.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
                "app/views.py": f'from .routers import router\n@router.get("/")\n{ENDPOINT}',
            },
            id="relative-import",
        ),
        pytest.param(
            {
                "app/api/__init__.py": "from .routers import router\n",
                "app/api/routers.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
                "app/views.py": f'from app.api import router\n@router.get("/")\n{ENDPOINT}',
            },
            id="re-export",
        ),
        pytest.param(
            {
                "app/api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
                "app/views.py": f'from app import api\n@api.router.get("/")\n{ENDPOINT}',
            },
            id="module-attribute",
        ),
        pytest.param(
            {
                "app/api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
                "app/views.py": f'import app.api\n@app.api.router.get("/")\n{ENDPOINT}',
            },
            id="imported-module-attribute",
        ),
        pytest.param(
            {
                "app/base.py": "import fastapi\nclass BaseRouter(fastapi.APIRouter): ...\n",
                "app/custom.py": "from app.base import BaseRouter\nclass Router(BaseRouter): ...\n",
                "app/views.py": (
                    f'from app.custom import Router\nrouter = Router()\n@router.get("/")\n{ENDPOINT}'
                ),
            },
            id="transitive-subclass-across-modules",
        ),
        pytest.param(
            {
                "app/base.py": "import fastapi\nclass BaseRouter(fastapi.APIRouter, Generic[T]): ...\n",
                "app/custom.py": "from app.base import BaseRouter\nclass Router(BaseRouter[User]): ...\n",
                "app/views.py": (
                    f'from app.custom import Router\nrouter = Router()\n@router.get("/")\n{ENDPOINT}'
                ),
            },
            id="generic-subclass-across-modules",
        ),
        pytest.param(
            {
                "app/base.py": "from fastapi import FastAPI\nclass App(FastAPI): ...\n",
                "app/core/__init__.py": "from app.base import App\n",
                "app/views.py": f'from app.core import App\napp = App()\n@app.get("/")\n{ENDPOINT}',
            },
            id="re-exported-subclass",
        ),
    ],
)
def test_endpoint_across_modules_is_skipped(tmp_path: Path, files: dict[str, str]) -> None:
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "views.py", ["fastapi"]) == set()


def test_endpoint_in_package_init_is_skipped(tmp_path: Path) -> None:
    source = f'from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/")\n{ENDPOINT}'
    write_project(tmp_path, PACKAGE | {"app/api/__init__.py": source})
    assert mutations(tmp_path / "app" / "api" / "__init__.py", ["fastapi"]) == set()


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            {
                "app/routers.py": "router = make()\n",
                "app/views.py": f'from app.routers import router\n@router.get("/")\n{ENDPOINT}',
            },
            id="imported-unknown-router",
        ),
        pytest.param(
            {"app/views.py": f'from app.missing import router\n@router.get("/")\n{ENDPOINT}'},
            id="missing-module",
        ),
        pytest.param(
            {
                "app/a.py": "from app.b import router\n",
                "app/b.py": "from app.a import router\n",
                "app/views.py": f'from app.a import router\n@router.get("/")\n{ENDPOINT}',
            },
            id="import-cycle",
        ),
        pytest.param(
            {
                "app/a.py": "from app.b import B\nclass A(B): ...\n",
                "app/b.py": "from app.a import A\nclass B(A): ...\n",
                "app/views.py": f'from app.a import A\nrouter = A()\n@router.get("/")\n{ENDPOINT}',
            },
            id="inheritance-cycle",
        ),
        pytest.param(
            {
                "app/base.py": "class Router: ...\n",
                "app/views.py": (
                    f'from app.base import Router\nrouter = Router()\n@router.get("/")\n{ENDPOINT}'
                ),
            },
            id="project-class-not-from-fastapi",
        ),
        pytest.param(
            {
                "app/base.py": "",
                "app/views.py": (
                    f'from app.base import Router\nrouter = Router()\n@router.get("/")\n{ENDPOINT}'
                ),
            },
            id="class-missing-in-module",
        ),
    ],
)
def test_unresolved_across_modules_is_mutated(tmp_path: Path, files: dict[str, str]) -> None:
    write_project(tmp_path, PACKAGE | files)
    expected = mutations(tmp_path / "app" / "views.py", [])
    assert mutations(tmp_path / "app" / "views.py", ["fastapi"]) == expected
    assert CORE_ENDPOINT_MUTATIONS <= expected


def test_undecodable_module_is_mutated(tmp_path: Path) -> None:
    write_project(
        tmp_path,
        PACKAGE | {"app/views.py": f'from app.broken import router\n@router.get("/")\n{ENDPOINT}'},
    )
    (tmp_path / "app" / "broken.py").write_bytes(b"\xff\xfe\x00")
    assert mutations(tmp_path / "app" / "views.py", ["fastapi"]) == CORE_ENDPOINT_MUTATIONS


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'from faststream.kafka.fastapi import KafkaRouter\nrouter = KafkaRouter("localhost")\n'
            f'@router.get("/")\n{ENDPOINT}',
            id="faststream-kafka-router",
        ),
        pytest.param(
            "from faststream.rabbit.fastapi import RabbitRouter\nrouter = RabbitRouter()\n"
            f'@router.post("/")\n{ENDPOINT}',
            id="faststream-rabbit-router",
        ),
        pytest.param(
            "from faststream._internal.fastapi.router import StreamRouter\n"
            "class Router(StreamRouter): ...\n"
            f'router = Router()\n@router.get("/")\n{ENDPOINT}',
            id="project-subclass-of-faststream-router",
        ),
        pytest.param(
            "from faststream_fastapi import KafkaRouter\nrouter = KafkaRouter()\n"
            f'@router.get("/")\n{ENDPOINT}',
            id="faststream-fastapi-package",
        ),
    ],
)
def test_third_party_router_endpoint_is_skipped(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == set()


def test_faststream_broker_router_is_not_an_app(tmp_path: Path) -> None:
    source = f'from faststream.kafka import KafkaRouter\nrouter = KafkaRouter()\n@router.get("/")\n{ENDPOINT}'
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == CORE_ENDPOINT_MUTATIONS


def test_app_classes_are_injectable(tmp_path: Path) -> None:
    source = f'from mylib import Api\napi = Api()\n@api.get("/")\n{ENDPOINT}'
    write_project(tmp_path, {"main.py": source})
    plugin = FastAPIPlugin(app_classes=["mylib.Api"])
    assert find_mutations(tmp_path / "main.py", [plugin]) == set()
    assert find_mutations(tmp_path / "main.py", [FastAPIPlugin()]) == CORE_ENDPOINT_MUTATIONS


PROVIDER = "def get_user(token: int | None) -> User: ...\n"

# The return annotation of a provider is skipped, its parameters are mutated.
PROVIDER_PARAMETER_MUTATIONS = {("RemoveOptional", "int | None", "int")}
CORE_PROVIDER_MUTATIONS = PROVIDER_PARAMETER_MUTATIONS | {("AddOptional", "User", "User | None")}

FASTAPI_IMPORTS = "from typing import Annotated\nfrom fastapi import Depends, FastAPI, Security\n"


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param("def view(user: Annotated[User, Depends(get_user)]): ...\n", id="annotated"),
        pytest.param("def view(user=Depends(get_user)): ...\n", id="default-value"),
        pytest.param(
            'def view(user: Annotated[User, Security(get_user, scopes=["me"])]): ...\n',
            id="security",
        ),
        pytest.param("def view(user=Depends(dependency=get_user)): ...\n", id="keyword-argument"),
        pytest.param(
            "def view(user=Depends(use_cache=False, dependency=get_user)): ...\n",
            id="keyword-after-keyword",
        ),
        pytest.param("UserDep = Annotated[User, Depends(get_user)]\n", id="type-alias"),
        pytest.param(
            'app = FastAPI()\n@app.get("/", dependencies=[Depends(get_user)])\ndef view(): ...\n',
            id="route-dependencies",
        ),
        pytest.param("app = FastAPI(dependencies=[Depends(get_user)])\n", id="app-dependencies"),
        pytest.param(
            "import fastapi\ndef view(user=fastapi.Depends(get_user)): ...\n",
            id="module-qualified-marker",
        ),
        pytest.param(
            "from fastapi.params import Depends as D\ndef view(user=D(get_user)): ...\n",
            id="params-module-marker",
        ),
        pytest.param(
            "app = FastAPI()\ndef test() -> None:\n    app.dependency_overrides[other] = get_user\n",
            id="override-value",
        ),
        pytest.param(
            "app = FastAPI()\napp.dependency_overrides[get_user] = override\n", id="override-key"
        ),
        pytest.param(
            "def view(user=Depends(get_user)): ...\ncall(get_user=1)\n",
            id="keyword-name-is-not-a-reference",
        ),
    ],
)
def test_provider_return_is_skipped(tmp_path: Path, usage: str) -> None:
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{PROVIDER}{usage}"})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == PROVIDER_PARAMETER_MUTATIONS


def test_async_provider_return_is_skipped(tmp_path: Path) -> None:
    usage = "def view(user=Depends(get_user)): ...\n"
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}async {PROVIDER}{usage}"})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == PROVIDER_PARAMETER_MUTATIONS


CHECKER = "class Checker:\n    def __call__(self, token: int | None) -> User: ...\n"


def test_callable_instance_provider_return_is_skipped(tmp_path: Path) -> None:
    usage = "checker = Checker()\ndef view(user=Depends(checker)): ...\n"
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{CHECKER}{usage}"})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == PROVIDER_PARAMETER_MUTATIONS


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(
            "checker = Checker()\ndef view(user=Depends(checker)): ...\nchecker(1)\n",
            id="instance-called-directly",
        ),
        pytest.param("def view(user=Depends(Checker)): ...\n", id="class-as-provider"),
        pytest.param(
            "from mylib import Other\nchecker = Other()\ndef view(user=Depends(checker)): ...\n",
            id="instance-of-library-class",
        ),
    ],
)
def test_callable_instance_provider_used_otherwise_is_mutated(tmp_path: Path, usage: str) -> None:
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{CHECKER}{usage}"})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == CORE_PROVIDER_MUTATIONS


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param("def view(user=Depends(get_user)): ...\nget_user(1)\n", id="called-directly"),
        pytest.param(
            "def view(user=Depends(get_user)): ...\nasync def test():\n    await get_user(1)\n",
            id="awaited-directly",
        ),
        pytest.param(
            "def view(user=Depends(get_user)): ...\nget_user.cache_clear()\n",
            id="attribute-reference",
        ),
        pytest.param(
            "def view(user=Depends(get_user)): ...\nalias = get_user\n", id="assigned-value"
        ),
        pytest.param(
            "def view(user=Depends(get_user)): ...\nprint(user=get_user)\n",
            id="keyword-argument-value",
        ),
        pytest.param("from mylib import Depends as Other\ndef view(user=Other(get_user)): ...\n", id="other-marker"),
        pytest.param("def view(user: Annotated[User, Depends()]): ...\n", id="marker-without-argument"),
        pytest.param("def view(user=Depends(use_cache=False)): ...\n", id="marker-keywords-only"),
        pytest.param("def view(user=Depends(make(get_user))): ...\n", id="argument-not-a-name"),
        pytest.param("def view(user=Depends(missing)): ...\n", id="unknown-name"),
        pytest.param("def view(user=Depends(lambda: 1)): ...\n", id="lambda-argument"),
        pytest.param("def view(user=Depends(typing.cast)): ...\n", id="library-function"),
        pytest.param(
            "holder.dependency_overrides[other] = get_user\n", id="override-of-unknown-receiver"
        ),
        pytest.param("cache = {}\ncache[other] = get_user\n", id="plain-subscript-assignment"),
        pytest.param(
            "app = FastAPI()\napp.dependency_overrides[a] = app.dependency_overrides[b] = get_user\n",
            id="chained-assignment",
        ),
        pytest.param(
            "app = FastAPI()\napp.dependency_overrides[other]: Any = get_user\n",
            id="annotated-assignment",
        ),
        pytest.param(
            "app = FastAPI()\napp.dependency_overrides = get_user\n", id="override-mapping-replaced"
        ),
        pytest.param("view(Depends(get_user)())\n", id="marker-called-again"),
    ],
)
def test_provider_used_otherwise_is_mutated(tmp_path: Path, usage: str) -> None:
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{PROVIDER}{usage}"})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == CORE_PROVIDER_MUTATIONS


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f"{FASTAPI_IMPORTS}def outer() -> None:\n    {PROVIDER}"
            "    def view(user=Depends(get_user)): ...\n",
            id="nested-function",
        ),
        pytest.param(
            f"{FASTAPI_IMPORTS}class Service:\n    @staticmethod\n    {PROVIDER}"
            "def view(user=Depends(Service.get_user)): ...\n",
            id="method",
        ),
        pytest.param(
            f"{FASTAPI_IMPORTS}class Outer:\n    {CHECKER.replace(chr(10) + '    ', chr(10) + '        ')}"
            "def view(user=Depends(Outer.Checker())): ...\n",
            id="nested-class-call",
        ),
        pytest.param(f"{FASTAPI_IMPORTS}{PROVIDER}", id="unused"),
    ],
)
def test_other_functions_are_not_providers(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["fastapi"]) == CORE_PROVIDER_MUTATIONS


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            {
                "app/deps.py": PROVIDER,
                "app/views.py": f"{FASTAPI_IMPORTS}from app.deps import get_user\n"
                "def view(user=Depends(get_user)): ...\n",
            },
            id="imported",
        ),
        pytest.param(
            {
                "app/deps.py": PROVIDER,
                "app/views.py": f"{FASTAPI_IMPORTS}from app import deps\n"
                "def view(user=Depends(deps.get_user)): ...\n",
            },
            id="module-attribute",
        ),
        pytest.param(
            {
                "app/api/__init__.py": "from app.deps import get_user\n",
                "app/deps.py": PROVIDER,
                "app/views.py": f"{FASTAPI_IMPORTS}from app.api import get_user\n"
                "def view(user=Depends(get_user)): ...\n",
            },
            id="re-export",
        ),
        pytest.param(
            {
                "app/deps.py": PROVIDER,
                "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "app/tests.py": "from app.main import app\nfrom app.deps import get_user\n"
                "app.dependency_overrides[other] = get_user\n",
            },
            id="override-of-imported-app",
        ),
    ],
)
def test_provider_across_modules_return_is_skipped(tmp_path: Path, files: dict[str, str]) -> None:
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "deps.py", ["fastapi"]) == PROVIDER_PARAMETER_MUTATIONS
    assert mutations(tmp_path / "app" / "deps.py", []) == CORE_PROVIDER_MUTATIONS


@pytest.mark.parametrize(
    "caller",
    [
        pytest.param("from app.deps import get_user\nget_user(1)\n", id="imported-call"),
        pytest.param("from app import deps\ndeps.get_user(1)\n", id="module-attribute-call"),
        pytest.param("import app.deps\napp.deps.get_user(1)\n", id="dotted-module-call"),
    ],
)
def test_provider_called_from_other_module_is_mutated(tmp_path: Path, caller: str) -> None:
    files = {
        "app/deps.py": PROVIDER,
        "app/views.py": f"{FASTAPI_IMPORTS}from app.deps import get_user\n"
        "def view(user=Depends(get_user)): ...\n",
        "app/checks.py": caller,
    }
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "deps.py", ["fastapi"]) == CORE_PROVIDER_MUTATIONS


def test_unreadable_module_is_not_scanned(tmp_path: Path) -> None:
    usage = "def view(user=Depends(get_user)): ...\n"
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{PROVIDER}{usage}"})
    (tmp_path / "broken.py").write_bytes(b"\xff\xfe\x00")
    assert mutations(tmp_path / "main.py", ["fastapi"]) == PROVIDER_PARAMETER_MUTATIONS


def test_providers_are_unknown_before_scan(tmp_path: Path) -> None:
    usage = "def view(user=Depends(get_user)): ...\n"
    write_project(tmp_path, {"main.py": f"{FASTAPI_IMPORTS}{PROVIDER}{usage}"})
    operators = OperatorRegistry().enabled({})
    finder = MutationFinder(operators, Registry(), [FastAPIPlugin()])
    found = {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(tmp_path / "main.py")
        for mutation in finder.find(annotation)
    }
    assert found == CORE_PROVIDER_MUTATIONS
