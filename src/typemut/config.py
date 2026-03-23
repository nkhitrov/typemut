"""TOML config parsing for typemut."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OperatorsConfig:
    remove_union_member: bool = True
    swap_literal_value: bool = True
    swap_sibling_type: bool = True
    strip_annotated: bool = True
    remove_optional: bool = True
    add_optional: bool = True
    swap_container_type: bool = True
    typevar_variance: bool = True


@dataclass
class Config:
    module_path: str = "src"
    test_command: str = "mypy src/"
    timeout: int = 30
    excluded_modules: list[str] = field(default_factory=list)
    skip_comments: list[str] = field(
        default_factory=lambda: ["type: ignore", "pragma: no mutate"]
    )
    operators: OperatorsConfig = field(default_factory=OperatorsConfig)
    db_path: str = "typemut.sqlite"


def load_config(path: Path) -> Config:
    """Load config from a TOML file."""
    text = path.read_text()
    raw = tomllib.loads(text)

    section = raw.get("typemut", {})
    ops_raw = section.pop("operators", {})

    operators = OperatorsConfig(
        remove_union_member=ops_raw.get("remove-union-member", True),
        swap_literal_value=ops_raw.get("swap-literal-value", True),
        swap_sibling_type=ops_raw.get("swap-sibling-type", True),
        strip_annotated=ops_raw.get("strip-annotated", True),
        remove_optional=ops_raw.get("remove-optional", True),
        add_optional=ops_raw.get("add-optional", True),
        swap_container_type=ops_raw.get("swap-container-type", True),
        typevar_variance=ops_raw.get("typevar-variance", True),
    )

    return Config(
        module_path=section.get("module-path", "src"),
        test_command=section.get("test-command", "mypy src/"),
        timeout=section.get("timeout", 30),
        excluded_modules=section.get("excluded-modules", []),
        skip_comments=section.get(
            "skip-comments", ["type: ignore", "pragma: no mutate"]
        ),
        operators=operators,
        db_path=section.get("db", "typemut.sqlite"),
    )
