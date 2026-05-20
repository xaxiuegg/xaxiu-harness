"""Precedence resolver for OperatorConfig (Wave 7).

Resolution order (later wins on conflict):
    1. Built-in defaults  (from OperatorConfig field defaults)
    2. Adapter YAML       (adapter.operator section)
    3. Environment vars   (HARNESS_*)
    4. CLI flags          (passed at invocation)
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from harness.operator.modes import OperatorConfig

__all__ = ["resolve_operator_config", "ENV_VAR_MAP"]


# CLI option name -> env var name (the YAML key is identical to the CLI option)
ENV_VAR_MAP: dict[str, str] = {
    "mode": "HARNESS_MODE",
    "escalation_threshold": "HARNESS_ESCALATION_THRESHOLD",
    "engine_fill": "HARNESS_ENGINE_FILL",
    "max_parallel_supervisors": "HARNESS_MAX_PARALLEL_SUPERVISORS",
    "explore_on_uncertainty": "HARNESS_EXPLORE_ON_UNCERTAINTY",
    "observer_cadence_minutes": "HARNESS_OBSERVER_CADENCE_MINUTES",
    "profile": "HARNESS_PROFILE",
}


def _coerce_int(value: Any) -> Any:
    """Best-effort int coercion for env-var strings; returns value unchanged on failure."""
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


def _read_env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field_name, env_name in ENV_VAR_MAP.items():
        raw = env.get(env_name)
        if raw is None or raw == "":
            continue
        if field_name in ("max_parallel_supervisors", "observer_cadence_minutes"):
            out[field_name] = _coerce_int(raw)
        else:
            out[field_name] = raw
    return out


def resolve_operator_config(
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    adapter_yaml: Mapping[str, Any] | None = None,
) -> OperatorConfig:
    """Resolve the operator config from all precedence layers.

    Each layer is optional.  Later layers override earlier ones on the
    fields they touch.  Unknown fields in any layer raise ``ValueError``
    via Pydantic's ``extra='forbid'``.

    Args:
        cli_overrides: highest priority — flag values from the active CLI invocation.
            ``None`` values are treated as "not provided" and skipped.
        env: environment dict (defaults to ``os.environ``).  Only ``HARNESS_*``
            entries that map to known fields are read.
        adapter_yaml: dict from the active adapter's ``operator:`` section.
    """
    if env is None:
        env = os.environ

    accumulated: dict[str, Any] = {}

    if adapter_yaml:
        accumulated.update({k: v for k, v in dict(adapter_yaml).items() if v is not None})

    accumulated.update(_read_env_overrides(env))

    if cli_overrides:
        accumulated.update({k: v for k, v in dict(cli_overrides).items() if v is not None})

    return OperatorConfig(**accumulated)
