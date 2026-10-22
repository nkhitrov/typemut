"""Tests for the FastStream plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

from typemut.discovery import AnnotationFinder
from typemut.mutations import MutationFinder
from typemut.operators import OperatorRegistry
from typemut.plugins import PluginRegistry
from typemut.registry import Registry

HANDLER = "async def handle(msg: str | None) -> str: ...\n"

CORE_HANDLER_MUTATIONS = {
    ("RemoveOptional", "str | None", "str"),
    ("AddOptional", "str", "str | None"),
}

KAFKA = 'from faststream.kafka import KafkaBroker\nbroker = KafkaBroker("localhost:9092")\n'


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
        pytest.param(f'{KAFKA}@broker.subscriber("in-topic")\n{HANDLER}', id="kafka-subscriber"),
        pytest.param(
            f'{KAFKA}@broker.subscriber("in")\n@broker.publisher("out")\n{HANDLER}',
            id="stacked-publisher",
        ),
        pytest.param(
            f'{KAFKA}publisher = broker.publisher("out")\n@publisher\n@broker.subscriber("in")\n'
            f"{HANDLER}",
            id="publisher-object-on-top",
        ),
        pytest.param(
            'from faststream.rabbit import RabbitBroker\nbroker = RabbitBroker("amqp://")\n'
            f'@broker.subscriber("test-queue")\n{HANDLER}',
            id="rabbit",
        ),
        pytest.param(
            "from faststream.redis import RedisBroker\nbroker = RedisBroker()\n"
            f'@broker.subscriber(channel="test")\n{HANDLER}',
            id="redis",
        ),
        pytest.param(
            "from faststream.nats import NatsBroker\nnats_broker = NatsBroker()\n"
            f'@nats_broker.subscriber("user.get")\n{HANDLER}',
            id="nats",
        ),
        pytest.param(
            "from faststream.confluent import KafkaBroker\nbroker = KafkaBroker()\n"
            f'@broker.subscriber("test")\n{HANDLER}',
            id="confluent",
        ),
        pytest.param(
            "import faststream.kafka\nbroker = faststream.kafka.KafkaBroker()\n"
            f'@broker.subscriber("test")\n{HANDLER}',
            id="module-qualified-broker",
        ),
        pytest.param(
            "from faststream.kafka.broker.broker import KafkaBroker as KB\nbroker = KB()\n"
            f'@broker.subscriber("test")\n{HANDLER}',
            id="defining-module-aliased",
        ),
        pytest.param(
            "from faststream.kafka import KafkaRouter\nrouter = KafkaRouter()\n"
            f'@router.subscriber("test")\n{HANDLER}',
            id="router",
        ),
        pytest.param(
            'from faststream.kafka.fastapi import KafkaRouter\nrouter = KafkaRouter("localhost")\n'
            f'@router.subscriber("test")\n@router.publisher("response")\n{HANDLER}',
            id="fastapi-integration-router",
        ),
        pytest.param(
            "from faststream_fastapi import KafkaRouter\nrouter = KafkaRouter()\n"
            f'@router.subscriber("test")\n{HANDLER}',
            id="faststream-fastapi-package",
        ),
        pytest.param(
            "from faststream.kafka import KafkaBroker\n"
            "class Broker(KafkaBroker): ...\n"
            "broker = Broker()\n"
            f'@broker.subscriber("test")\n{HANDLER}',
            id="project-subclass",
        ),
        pytest.param(
            "from faststream.kafka import KafkaBroker\n"
            "def register(broker: KafkaBroker) -> None:\n"
            '    @broker.subscriber("test")\n'
            f"    {HANDLER}",
            id="annotated-parameter",
        ),
        pytest.param(
            f"from faststream import FastStream\napp = FastStream()\n@app.on_startup\n{HANDLER}",
            id="on-startup",
        ),
        pytest.param(
            f"from faststream import FastStream\napp = FastStream()\n@app.after_startup\n{HANDLER}",
            id="after-startup",
        ),
        pytest.param(
            f"from faststream import FastStream\napp = FastStream()\n@app.on_shutdown\n{HANDLER}",
            id="on-shutdown",
        ),
        pytest.param(
            "from faststream.asgi import AsgiFastStream\napp = AsgiFastStream()\n"
            f"@app.after_shutdown\n{HANDLER}",
            id="asgi-after-shutdown",
        ),
        pytest.param(
            "from faststream.kafka.fastapi import KafkaRouter\nrouter = KafkaRouter()\n"
            f"@router.after_startup\n{HANDLER}",
            id="fastapi-router-after-startup",
        ),
        pytest.param(
            f'{HANDLER}{KAFKA}broker.subscriber("test")(handle)\n',
            id="registered-by-call",
        ),
        pytest.param(
            f"{HANDLER}{KAFKA.replace('KafkaBroker(', 'KafkaBroker(parser=handle, ')}",
            id="broker-parser",
        ),
        pytest.param(
            f'{HANDLER}{KAFKA}@broker.subscriber("test", decoder=handle)\n'
            "async def other() -> None: ...\n",
            id="subscriber-decoder",
        ),
        pytest.param(
            f"{HANDLER}from faststream.rabbit import RabbitBroker\n"
            "broker = RabbitBroker(middlewares=(Middleware, handle))\n",
            id="middleware-tuple",
        ),
        pytest.param(
            f"{HANDLER}from faststream.rabbit import RabbitBroker\n"
            "broker = RabbitBroker(middlewares=[handle])\n",
            id="middleware-list",
        ),
        pytest.param(
            f"{HANDLER}from faststream.rabbit import RabbitBroker\n"
            "broker = RabbitBroker(middlewares=(handle))\n",
            id="middleware-parenthesized",
        ),
        pytest.param(
            f"{HANDLER}from faststream import FastStream\napp = FastStream(broker, on_startup=[handle])\n",
            id="app-hook-argument",
        ),
        pytest.param(
            f"{HANDLER}from faststream import FastStream\napp = FastStream(lifespan=handle)\n",
            id="app-lifespan",
        ),
        pytest.param(
            f"{HANDLER}from faststream.kafka import KafkaRoute, KafkaRouter\n"
            'router = KafkaRouter(handlers=(KafkaRoute(handle, "test"),))\n',
            id="route",
        ),
        pytest.param(
            f"{HANDLER}from faststream.kafka import KafkaRoute\nroute = KafkaRoute(call=handle)\n",
            id="route-call-keyword",
        ),
        pytest.param(
            f'{HANDLER}from faststream.kafka import KafkaPublisher\np = KafkaPublisher("t", middlewares=[handle])\n',
            id="route-publisher-middleware",
        ),
        pytest.param(
            f"{HANDLER}from typing import Annotated\nfrom faststream import Depends\n"
            "async def consume(user: Annotated[str, Depends(handle)]) -> None: ...\n",
            id="depends-provider",
        ),
        pytest.param(
            f"{HANDLER}from typing import Annotated\nfrom fast_depends import Depends\n"
            "Session = Annotated[str, Depends(handle)]\n",
            id="fast-depends-provider-alias",
        ),
    ],
)
def test_framework_called_signature_is_skipped(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["faststream"]) == set()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(HANDLER, id="undecorated"),
        pytest.param(f'@subscriber("test")\n{HANDLER}', id="bare-subscriber-name"),
        pytest.param(f'{KAFKA}@broker.request("test")\n{HANDLER}', id="not-a-handler-method"),
        pytest.param(
            f'class KafkaBroker: ...\nbroker = KafkaBroker()\n@broker.subscriber("t")\n{HANDLER}',
            id="local-class-named-like-broker",
        ),
        pytest.param(
            f'from mylib import KafkaBroker\nbroker = KafkaBroker()\n@broker.subscriber("t")\n{HANDLER}',
            id="broker-name-from-other-package",
        ),
        pytest.param(
            f'from faststream.kafka import KafkaBroker\nbroker = make()\n@broker.subscriber("t")\n{HANDLER}',
            id="factory-call",
        ),
        pytest.param(
            f'{KAFKA}@broker.subscriber.other("t")\n{HANDLER}',
            id="attribute-of-method",
        ),
        pytest.param(
            f"from faststream import FastStream\napp = FastStream()\n@app.on_broker_shutdown\n{HANDLER}",
            id="router-hook-on-application",
        ),
        pytest.param(
            f"{KAFKA}@broker.on_startup\n{HANDLER}",
            id="application-hook-on-broker",
        ),
        pytest.param(f"{HANDLER}{KAFKA}handle(parser=handle)\n", id="parser-of-other-call"),
        pytest.param(
            f"{HANDLER}from mylib import Broker\nbroker = Broker(parser=handle)\n",
            id="parser-of-other-class",
        ),
        pytest.param(
            f"{HANDLER}{KAFKA}x = KafkaBroker(timeout=handle, parser=handle.parse)\n",
            id="other-keyword-and-attribute",
        ),
        pytest.param(
            f"{HANDLER}{KAFKA}x = KafkaBroker(*handle, **handle)\n",
            id="star-arguments",
        ),
        pytest.param(
            f"{HANDLER}{KAFKA}x = KafkaBroker(handle)\n",
            id="positional-broker-argument",
        ),
        pytest.param(
            f'{HANDLER}{KAFKA}x = broker.subscriber("t")\nx(handle)\n',
            id="registered-through-variable",
        ),
        pytest.param(
            f'{HANDLER}{KAFKA}broker.subscriber("t").call(handle)\n',
            id="attribute-after-registrar",
        ),
        pytest.param(
            f'{HANDLER}{KAFKA}broker.subscriber("t")[handle]\n', id="subscript-after-registrar"
        ),
        pytest.param(
            f"{HANDLER}from faststream.kafka import KafkaRoute\nKafkaRoute()\n",
            id="route-without-arguments",
        ),
        pytest.param(
            f"{HANDLER}from faststream import Depends\nDepends(lambda: handle)\n",
            id="depends-on-lambda",
        ),
        pytest.param(
            f"{HANDLER}from faststream import FastStream\napp = FastStream(on_startup=handle())\n",
            id="hook-call-result",
        ),
        pytest.param(
            f"{HANDLER}import faststream\nfaststream.helpers[0](parser=handle)\n",
            id="subscripted-callee",
        ),
        pytest.param(
            f"{HANDLER}{KAFKA}async def main() -> None:\n    await broker.subscriber(parser=x)(y)\n",
            id="awaited-call",
        ),
    ],
)
def test_other_functions_are_mutated(tmp_path: Path, source: str) -> None:
    write_project(tmp_path, {"main.py": source})
    expected = mutations(tmp_path / "main.py", [])
    assert mutations(tmp_path / "main.py", ["faststream"]) == expected
    assert CORE_HANDLER_MUTATIONS <= expected


def test_body_annotations_are_mutated(tmp_path: Path) -> None:
    source = (
        f"{KAFKA}"
        '@broker.subscriber("test")\n'
        "async def handle(msg: str) -> None:\n"
        "    reply: str | None = None\n"
        "    def helper() -> int: ...\n"
    )
    write_project(tmp_path, {"main.py": source})
    assert mutations(tmp_path / "main.py", ["faststream"]) == {
        ("RemoveOptional", "str | None", "str"),
        ("AddOptional", "int", "int | None"),
    }


def test_registrations_follow_file_changes(tmp_path: Path) -> None:
    """The plugin re-reads a file's registrations when the file is parsed again."""
    plugin = PluginRegistry().get(["faststream"])
    operators = OperatorRegistry().enabled({})
    file = tmp_path / "main.py"
    write_project(tmp_path, {"main.py": f"{HANDLER}{KAFKA}x = KafkaBroker(parser=handle)\n"})
    registered = [
        mutation
        for annotation in AnnotationFinder().find(file)
        for mutation in MutationFinder(operators, Registry(), plugin).find(annotation)
    ]
    write_project(tmp_path, {"main.py": f"{HANDLER}{KAFKA}x = KafkaBroker()\n"})
    unregistered = {
        (mutation.operator, mutation.original, mutation.mutated)
        for annotation in AnnotationFinder().find(file)
        for mutation in MutationFinder(operators, Registry(), plugin).find(annotation)
    }
    assert registered == []
    assert unregistered == CORE_HANDLER_MUTATIONS


PACKAGE = {"app/__init__.py": ""}


def test_imported_broker_is_resolved(tmp_path: Path) -> None:
    files = {
        "app/brokers.py": KAFKA,
        "app/handlers.py": f'from app.brokers import broker\n@broker.subscriber("t")\n{HANDLER}',
    }
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "handlers.py", ["faststream"]) == set()


def test_broker_subclass_across_modules_is_resolved(tmp_path: Path) -> None:
    files = {
        "app/base.py": "from faststream.rabbit import RabbitBroker\nclass Broker(RabbitBroker): ...\n",
        "app/handlers.py": (
            f"{HANDLER}from app.base import Broker\nbroker = Broker(decoder=handle)\n"
        ),
    }
    write_project(tmp_path, PACKAGE | files)
    assert mutations(tmp_path / "app" / "handlers.py", ["faststream"]) == set()
