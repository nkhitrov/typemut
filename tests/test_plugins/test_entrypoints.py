"""Tests for the config-driven entrypoints plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.config import EntrypointsConfig
from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins.entrypoints import EntrypointsPlugin
from typemut.registry import Registry

HANDLER = "def handler(q: int | None) -> Schema: ...\n"
METHOD = "    def handler(self, q: int | None) -> Schema: ...\n"

HANDLER_MUTATIONS = {
    ("RemoveOptional", "int | None", "int"),
    ("AddOptional", "Schema", "Schema | None"),
}

DECORATORS = EntrypointsConfig(decorators=["mylib.rpc.*.method", "tasks.*"])
BASE_CLASSES = EntrypointsConfig(base_classes=["mylib.rpc.Endpoint"])
PARAMETER_TYPES = EntrypointsConfig(
    parameter_types=["mylib.rpc.Dependency", "mylib.rpc.Router.Dependency", "mylib.di.*"]
)
PACKAGE = {"app/__init__.py": ""}


def mutations(file: Path, config: EntrypointsConfig) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *file* (read from disk)."""
    operators = OperatorRegistry().enabled({})
    finder = MutationFinder(operators, Registry(), [EntrypointsPlugin(config)])
    return {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(file)
        for mutation in finder.find(annotation)
    }


def write_project(root: Path, files: dict[str, str]) -> None:
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


@pytest.mark.parametrize(
    ("config", "source"),
    [
        pytest.param(
            DECORATORS,
            f"from mylib.rpc import Router\nrpc = Router()\n@rpc.method()\n{HANDLER}",
            id="instance-method-call",
        ),
        pytest.param(
            DECORATORS,
            f"from mylib.rpc import Router\nrpc = Router()\n@rpc.method\nasync {HANDLER}",
            id="instance-method-without-call",
        ),
        pytest.param(
            DECORATORS,
            "from mylib.rpc import Router\n"
            "class AppRouter(Router): ...\n"
            "rpc = AppRouter()\n"
            f"@rpc.method()\n{HANDLER}",
            id="instance-of-project-subclass",
        ),
        pytest.param(
            DECORATORS,
            "from mylib import rpc\n"
            "def register(router: rpc.Router) -> None:\n"
            "    @router.method()\n"
            f"    {HANDLER}",
            id="annotated-parameter-receiver",
        ),
        pytest.param(
            DECORATORS,
            f"from tasks import task\n@cache\n@task\n{HANDLER}",
            id="imported-function",
        ),
        pytest.param(
            DECORATORS,
            f"import tasks\n@tasks.periodic(every=5)\n{HANDLER}",
            id="module-attribute-call",
        ),
        pytest.param(
            BASE_CLASSES,
            f"from mylib.rpc import Endpoint\nclass Items(Endpoint):\n{METHOD}",
            id="direct-base",
        ),
        pytest.param(
            BASE_CLASSES,
            f"from mylib import rpc\nclass Items(Mixin, rpc.Endpoint, metaclass=Meta):\n{METHOD}",
            id="module-qualified-base",
        ),
        pytest.param(
            BASE_CLASSES,
            "from mylib.rpc import Endpoint\n"
            "class Base(Endpoint): ...\n"
            f"class Items(Base):\n{METHOD}",
            id="transitive-base",
        ),
        pytest.param(
            BASE_CLASSES,
            f"from mylib.rpc import Endpoint\nclass Items(Endpoint):\n    @staticmethod\n{METHOD}",
            id="decorated-method",
        ),
        pytest.param(
            PARAMETER_TYPES,
            f"from mylib.rpc import Dependency\ndef handler(s: Dependency[Service]) -> Schema: ...\n",
            id="generic-marker",
        ),
        pytest.param(
            PARAMETER_TYPES,
            "from mylib.rpc import Router\n"
            "rpc = Router()\n"
            "def handler(s: Annotated[Service, rpc.Dependency()]) -> Schema: ...\n",
            id="marker-of-instance",
        ),
        pytest.param(
            PARAMETER_TYPES,
            "from mylib import di\ndef handler(s: list[di.Inject]) -> Schema: ...\n",
            id="nested-module-qualified-marker",
        ),
        pytest.param(
            PARAMETER_TYPES,
            "from mylib.rpc import Dependency\n"
            "def handler(s: (Dependency)[Service]) -> Schema: ...\n",
            id="parenthesized-marker",
        ),
    ],
)
def test_handler_signature_is_skipped(
    tmp_path: Path, config: EntrypointsConfig, source: str
) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", config) == set()


@pytest.mark.parametrize(
    ("config", "source"),
    [
        pytest.param(EntrypointsConfig(), f"@rpc.method()\n{HANDLER}", id="no-patterns"),
        pytest.param(DECORATORS, HANDLER, id="undecorated"),
        pytest.param(
            DECORATORS,
            f"from mylib.rpc import Router\nrpc = Router()\n@rpc.route()\n{HANDLER}",
            id="other-method",
        ),
        pytest.param(
            DECORATORS,
            f"from other import Router\nrpc = Router()\n@rpc.method()\n{HANDLER}",
            id="other-class",
        ),
        pytest.param(
            DECORATORS,
            f"from mylib.rpc import Router\nrpc = make()\n@rpc.method()\n{HANDLER}",
            id="unknown-receiver",
        ),
        pytest.param(
            DECORATORS,
            f"from mylib.rpc import Router\nrouters = [Router()]\n@routers[0].method()\n{HANDLER}",
            id="subscript-receiver",
        ),
        pytest.param(DECORATORS, f"@undefined\n{HANDLER}", id="unresolved-name"),
        pytest.param(DECORATORS, f"@(lambda f: f)\n{HANDLER}", id="expression-decorator"),
        pytest.param(BASE_CLASSES, f"class Items:\n{METHOD}", id="no-base"),
        pytest.param(
            BASE_CLASSES,
            f"from mylib.rpc import Endpoint\nclass Endpoint2(Other):\n{METHOD}",
            id="other-base",
        ),
        pytest.param(BASE_CLASSES, f"class Items(Unknown):\n{METHOD}", id="unresolved-base"),
        pytest.param(
            BASE_CLASSES,
            "from mylib.rpc import Endpoint\n"
            "class Items(Endpoint):\n"
            "    def method(self) -> None:\n"
            f"    {METHOD}",
            id="nested-function-in-method",
        ),
        pytest.param(BASE_CLASSES, HANDLER, id="module-function"),
        pytest.param(
            PARAMETER_TYPES,
            f"from mylib.rpc import Dependency\n{HANDLER}",
            id="marker-not-used",
        ),
        pytest.param(
            PARAMETER_TYPES,
            'from mylib.rpc import Dependency\ndef handler(q: int | None, s: "Dependency") -> Schema: ...\n',
            id="string-annotation",
        ),
        pytest.param(
            PARAMETER_TYPES,
            "from other import Dependency\n"
            "def handler(q: int | None, *args, s: Dependency) -> Schema: ...\n",
            id="other-marker",
        ),
    ],
)
def test_other_functions_are_mutated(
    tmp_path: Path, config: EntrypointsConfig, source: str
) -> None:
    write_project(tmp_path, {"main.py": source})
    assert HANDLER_MUTATIONS <= mutations(tmp_path / "main.py", config)


def test_body_annotations_are_mutated(tmp_path: Path) -> None:
    source = (
        "from mylib.rpc import Router\n"
        "rpc = Router()\n"
        "@rpc.method()\n"
        "def handler() -> None:\n"
        "    x: int | None = None\n"
        "    def helper() -> Schema: ...\n"
    )
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", DECORATORS) == HANDLER_MUTATIONS


@pytest.mark.parametrize(
    ("config", "files"),
    [
        pytest.param(
            DECORATORS,
            {
                "app/rpc.py": "from mylib.rpc import Router\nrpc = Router()\n",
                "app/views.py": f"from app.rpc import rpc\n@rpc.method()\n{HANDLER}",
            },
            id="imported-router",
        ),
        pytest.param(
            BASE_CLASSES,
            {
                "app/base.py": "from mylib import rpc\nclass Base(rpc.Endpoint): ...\n",
                "app/views.py": f"from app.base import Base\nclass Items(Base):\n{METHOD}",
            },
            id="base-from-other-module",
        ),
        pytest.param(
            PARAMETER_TYPES,
            {
                "app/rpc.py": "from mylib.rpc import Router\nrpc = Router()\n",
                "app/views.py": (
                    "from app.rpc import rpc\n"
                    "def handler(s: rpc.Dependency[Service]) -> Schema: ...\n"
                ),
            },
            id="marker-of-imported-instance",
        ),
    ],
)
def test_handler_across_modules_is_skipped(
    tmp_path: Path, config: EntrypointsConfig, files: dict[str, str]
) -> None:
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "views.py", config) == set()
