"""Fail-fast config loader — doc 11 §8: every `config/*.yaml` is validated
against its `config/schema/*.schema.json` counterpart at service boot.

Env-var interpolation: any string value of the exact form `${VAR_NAME}` is
replaced with `os.environ["VAR_NAME"]` (raises if unset). Only whole-value
placeholders are interpolated (matches `models.yaml`'s `gateway_url`).
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import jsonschema
import yaml


def _default_config_dir() -> Path:
    # `AWP_CONFIG_DIR` is authoritative when set (always set in containers —
    # see mcps/*/Dockerfile, deploy/docker-compose.dev.yml). The `__file__`
    # parent-traversal fallback only works in an editable/source checkout
    # (local dev via `uv run`, tests run from the repo): once this package is
    # `pip install`-ed non-editably, `__file__` points into site-packages,
    # not the repo, so relying on it there would silently resolve to the
    # wrong directory instead of failing loudly.
    env_dir = os.environ.get("AWP_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parents[2] / "config"


CONFIG_DIR = _default_config_dir()
SCHEMA_DIR = CONFIG_DIR / "schema"


class ConfigError(Exception):
    pass


def _interpolate(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        if var_name not in os.environ:
            raise ConfigError(f"config references unset env var: {var_name}")
        return os.environ[var_name]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


@functools.cache
def load_config(name: str, *, config_dir: Path | None = None) -> Any:
    """Load and schema-validate `config/{name}.yaml`. Cached per process.

    `config_dir` override exists for tests; production code should never pass it.
    """
    base = config_dir or CONFIG_DIR
    yaml_path = base / f"{name}.yaml"
    schema_path = base / "schema" / f"{name}.schema.json"

    if not yaml_path.exists():
        raise ConfigError(f"missing config file: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if schema_path.exists():
        import json

        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ConfigError(f"{yaml_path} failed schema validation: {exc.message}") from exc

    return _interpolate(data)


# Every config file expected to exist by Sprint 1's boot-validation set.
# Later sprints append their own file's name here as it's introduced.
BOOT_VALIDATED_CONFIGS: tuple[str, ...] = (
    "intents",
    "gates",
    "scopes",
    "routing",
    "sla",
    "models",
    "entitlements",
    "shortlist",
    "sources",
    "roles",
    "dev_users",
)


def validate_all() -> None:
    """Call at process startup (every agent/MCP server main.py). Fail fast."""
    errors: list[str] = []
    for name in BOOT_VALIDATED_CONFIGS:
        try:
            load_config(name)
        except ConfigError as exc:
            errors.append(str(exc))
    if errors:
        raise ConfigError("config validation failed:\n" + "\n".join(errors))


def get_dev_users() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = load_config("dev_users")
    return result


def get_gate(gate_name: str) -> dict[str, Any]:
    gates: dict[str, Any] = load_config("gates")
    if gate_name not in gates:
        raise ConfigError(f"unknown gate: {gate_name}")
    result: dict[str, Any] = gates[gate_name]
    return result


def get_required_scopes(server: str, tool: str) -> list[str]:
    scopes: dict[str, list[str]] = load_config("scopes")
    key = f"{server}.{tool}"
    result: list[str] = scopes.get(key, [])
    return result
