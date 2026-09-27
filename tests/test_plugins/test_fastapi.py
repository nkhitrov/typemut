"""Tests for the FastAPI plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.config import OperatorsConfig
from typemut.discovery import AnnotationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import MutationFinder, PluginRegistry
from typemut.registry import Registry

ENDPOINT = "def endpoint(q: int | None) -> RedirectResponse: ...\n"

CORE_ENDPOINT_MUTATIONS = {
    ("RemoveOptional", "int | None", "int"),
    ("AddOptional", "RedirectResponse", "RedirectResponse | None"),
}


def mutations(file: Path, plugins: list[str]) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *file* (read from disk)."""
    operators = OperatorRegistry().enabled(OperatorsConfig())
    loaded = PluginRegistry().get(plugins)
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
