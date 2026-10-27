"""Tests for the django-modern-rest (dmr) plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry

ENDPOINT = "    def post(self, parsed_body: Body[UserModel], q: int | None) -> UserModel: ...\n"

PARAMETER_MUTATIONS = {("RemoveOptional", "int | None", "int")}
RETURN_MUTATIONS = {("AddOptional", "UserModel", "UserModel | None")}

CONTROLLER = "from dmr import Body, Controller\n"
PACKAGE = {"app/__init__.py": ""}


def mutations(file: Path, plugins: list[str]) -> set[tuple[str, str, str]]:
    """Mutations of every annotation in *file* (read from disk)."""
    operators = OperatorRegistry().enabled({})
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
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n{ENDPOINT}",
            id="generic-controller",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller):\n{ENDPOINT}",
            id="plain-controller",
        ),
        pytest.param(
            "import dmr\n"
            f"class UserController(dmr.controller.Controller[MsgspecSerializer]):\n{ENDPOINT}",
            id="module-qualified-controller",
        ),
        pytest.param(
            "from dmr.streaming.sse import SSEController\n"
            f"class EventsController(SSEController[MsgspecSerializer]):\n{ENDPOINT}",
            id="sse-controller",
        ),
        pytest.param(
            "from dmr.streaming.jsonl import JsonLinesController\n"
            f"class EventsController(JsonLinesController[MsgspecSerializer]):\n{ENDPOINT}",
            id="jsonl-controller",
        ),
        pytest.param(
            f"{CONTROLLER}"
            "class Base(Controller[_SerializerT], Generic[_SerializerT]): ...\n"
            f"class UserController(LoggingMixin, Base[PydanticSerializer]):\n{ENDPOINT}",
            id="project-base-controller",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            f"    async{ENDPOINT[3:]}",
            id="async-endpoint",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            f"{ENDPOINT.replace('post', 'meta')}",
            id="meta-endpoint",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            f"    @(lambda method: method)\n{ENDPOINT}",
            id="expression-decorator",
        ),
        pytest.param(
            f"{CONTROLLER}from dmr import modify\n"
            "class UserController(Controller[PydanticSerializer]):\n"
            "    @modify(status_code=HTTPStatus.OK)\n"
            f"{ENDPOINT}",
            id="modify",
        ),
        pytest.param(
            f"{CONTROLLER}import dmr\n"
            "class UserController(Controller[PydanticSerializer]):\n"
            "    @dmr.modify.lazy(status_code=HTTPStatus.OK)\n"
            f"{ENDPOINT}",
            id="lazy-modify",
        ),
        pytest.param(
            "from dmr.streaming import modify\n"
            "class LoggingMixin:\n"
            "    @modify(status_code=HTTPStatus.OK)\n"
            f"{ENDPOINT.replace('post', 'create')}",
            id="streaming-modify",
        ),
        pytest.param(
            "import dmr.endpoint\n"
            "modify = dmr.endpoint.ModifyEndpoint(SmartResponse)\n"
            "class LoggingMixin:\n"
            "    @modify.lazy(lambda controller: {})\n"
            f"{ENDPOINT.replace('post', 'create')}",
            id="custom-lazy-modify",
        ),
        pytest.param(
            "from dmr.endpoint import modify\n"
            "class LoggingMixin:\n"
            "    @modify(status_code=HTTPStatus.OK)\n"
            f"{ENDPOINT.replace('post', 'create')}",
            id="modify-outside-controller",
        ),
    ],
)
def test_endpoint_return_is_skipped(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["dmr"]) == PARAMETER_MUTATIONS


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f"{CONTROLLER}from dmr import ResponseSpec, validate\n"
            "class UserController(Controller[PydanticSerializer]):\n"
            "    @validate(ResponseSpec(UserModel, status_code=HTTPStatus.OK))\n"
            f"{ENDPOINT}",
            id="validate",
        ),
        pytest.param(
            f"{CONTROLLER}from dmr import modify, validate\n"
            "class UserController(Controller[PydanticSerializer]):\n"
            "    @validate.lazy(lambda controller: ResponseSpec(UserModel))\n"
            f"{ENDPOINT}",
            id="lazy-validate",
        ),
        pytest.param(
            "from dmr.streaming import validate\n"
            "from dmr.streaming.sse import SSEController\n"
            "class EventsController(SSEController[MsgspecSerializer]):\n"
            "    @validate(streaming_response_spec(UserModel, content_type=ContentType.event_stream))\n"
            f"{ENDPOINT}",
            id="streaming-validate",
        ),
        pytest.param(
            f"{CONTROLLER}from dmr.endpoint import ValidateEndpoint\n"
            "validate: Final = ValidateEndpoint(SmartResponse)  # pragma: no mutate\n"
            "class APIController(Controller[PydanticFastSerializer]):\n"
            "    @validate(ResponseSpec(str, status_code=HTTPStatus.OK))\n"
            f"{ENDPOINT}",
            id="custom-validate",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            f"{ENDPOINT.replace('post', 'to_error')}",
            id="controller-api-override",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            f"{ENDPOINT.replace('post', 'options')}",
            id="django-options",
        ),
        pytest.param(
            f"{CONTROLLER}class UserController(Controller[PydanticSerializer]):\n"
            "    def helper(self) -> None:\n"
            f"    {ENDPOINT}",
            id="nested-function",
        ),
        pytest.param(f"class UserController(View):\n{ENDPOINT}", id="django-view"),
        pytest.param(
            "from dmr.security.jwt.views import ObtainTokensSyncController\n"
            f"class LoginController(ObtainTokensSyncController):\n{ENDPOINT}",
            id="library-endpoint-override",
        ),
        pytest.param(f"from dmr import Body\n{ENDPOINT[4:]}", id="module-function"),
        pytest.param(
            "from other import modify\n"
            "class LoggingMixin:\n"
            "    @modify(status_code=HTTPStatus.OK)\n"
            f"{ENDPOINT}",
            id="other-modify",
        ),
    ],
)
def test_other_signatures_are_mutated(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["dmr"]) == PARAMETER_MUTATIONS | RETURN_MUTATIONS


def test_class_attributes_and_body_are_mutated(tmp_path: Path) -> None:
    source = (
        f"{CONTROLLER}"
        "class UserController(Controller[PydanticSerializer]):\n"
        "    request: AuthenticatedHttpRequest | None\n"
        "    def get(self) -> UserModel:\n"
        "        user: UserModel | None = None\n"
    )
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["dmr"]) == {
        ("RemoveOptional", "AuthenticatedHttpRequest | None", "AuthenticatedHttpRequest"),
        ("RemoveOptional", "UserModel | None", "UserModel"),
    }


def test_streaming_endpoint_return_is_skipped(tmp_path: Path) -> None:
    source = (
        "from collections.abc import AsyncIterator\n"
        "from dmr.streaming.sse import SSEController, SSEvent\n"
        "class UserEventsController(SSEController[MsgspecSerializer]):\n"
        "    async def get(self) -> AsyncIterator[SSEvent[_User]]:\n"
        "        return self.produce_user_events()\n"
    )
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["dmr"]) == set()


def test_controller_from_other_module(tmp_path: Path) -> None:
    files = {
        "app/base.py": "import dmr\nclass BaseController(dmr.Controller[_S], Generic[_S]): ...\n",
        "app/views.py": (
            "from app.base import BaseController\n"
            f"class UserController(BaseController[PydanticSerializer]):\n{ENDPOINT}"
        ),
    }
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "views.py", ["dmr"]) == PARAMETER_MUTATIONS
