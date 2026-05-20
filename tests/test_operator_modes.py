"""Tests for the operator-modes config surface (Wave 7)."""

from __future__ import annotations

import pytest

from harness.operator import (
    DEFAULT_ENGINE_ROUTING,
    DEFAULT_ENGINE_SLOTS,
    OperatorConfig,
    OperatorMode,
    resolve_operator_config,
)


# ---------------------------------------------------------------------------
# OperatorConfig defaults
# ---------------------------------------------------------------------------

def test_default_config_safe() -> None:
    cfg = OperatorConfig()
    assert cfg.mode is OperatorMode.REVIEW_EACH
    assert cfg.escalation_threshold == "L5"
    assert cfg.engine_fill == "aggressive"
    assert cfg.max_parallel_supervisors == 4
    assert cfg.explore_on_uncertainty == "dispatch_alternatives"
    assert cfg.profile == "technical"
    assert cfg.engine_routing == DEFAULT_ENGINE_ROUTING
    assert cfg.engine_slots == DEFAULT_ENGINE_SLOTS


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_mode_rejected() -> None:
    with pytest.raises(Exception):  # Pydantic ValidationError
        OperatorConfig(mode="not_a_mode")  # type: ignore[arg-type]


def test_max_parallel_supervisors_range() -> None:
    with pytest.raises(Exception):
        OperatorConfig(max_parallel_supervisors=0)
    with pytest.raises(Exception):
        OperatorConfig(max_parallel_supervisors=17)
    OperatorConfig(max_parallel_supervisors=1)
    OperatorConfig(max_parallel_supervisors=16)


def test_observer_cadence_range() -> None:
    with pytest.raises(Exception):
        OperatorConfig(observer_cadence_minutes=4)
    with pytest.raises(Exception):
        OperatorConfig(observer_cadence_minutes=1441)


def test_extra_field_rejected() -> None:
    with pytest.raises(Exception):
        OperatorConfig(unknown_field="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Precedence: CLI > env > YAML > default
# ---------------------------------------------------------------------------

def test_resolver_empty_yields_defaults() -> None:
    cfg = resolve_operator_config(env={})
    assert cfg.mode is OperatorMode.REVIEW_EACH


def test_yaml_only_override() -> None:
    cfg = resolve_operator_config(
        env={},
        adapter_yaml={"mode": "full_dev_authority"},
    )
    assert cfg.mode is OperatorMode.FULL_DEV_AUTHORITY


def test_env_overrides_yaml() -> None:
    cfg = resolve_operator_config(
        env={"HARNESS_MODE": "dry_run"},
        adapter_yaml={"mode": "full_dev_authority"},
    )
    assert cfg.mode is OperatorMode.DRY_RUN


def test_cli_overrides_env_and_yaml() -> None:
    cfg = resolve_operator_config(
        cli_overrides={"mode": "review_each"},
        env={"HARNESS_MODE": "full_dev_authority"},
        adapter_yaml={"mode": "dry_run"},
    )
    assert cfg.mode is OperatorMode.REVIEW_EACH


def test_cli_none_is_treated_as_unset() -> None:
    """``None`` CLI values fall through to env/YAML, don't override them."""
    cfg = resolve_operator_config(
        cli_overrides={"mode": None, "engine_fill": "conservative"},
        env={"HARNESS_MODE": "full_dev_authority"},
    )
    assert cfg.mode is OperatorMode.FULL_DEV_AUTHORITY
    assert cfg.engine_fill == "conservative"


def test_env_int_coercion() -> None:
    cfg = resolve_operator_config(env={"HARNESS_MAX_PARALLEL_SUPERVISORS": "8"})
    assert cfg.max_parallel_supervisors == 8


def test_env_keys_ignored_if_unmapped() -> None:
    cfg = resolve_operator_config(env={"HARNESS_UNKNOWN_KEY": "value"})
    assert cfg.mode is OperatorMode.REVIEW_EACH  # default; unknown key didn't poison


# ---------------------------------------------------------------------------
# Engine routing / slots customization
# ---------------------------------------------------------------------------

def test_engine_routing_can_be_overridden() -> None:
    cfg = resolve_operator_config(
        env={},
        adapter_yaml={"engine_routing": {"developing": "swarm/deepseek"}},
    )
    # Override REPLACES the field; if user wants merge, they specify full dict.
    assert cfg.engine_routing == {"developing": "swarm/deepseek"}


def test_engine_slots_can_be_overridden() -> None:
    cfg = resolve_operator_config(
        env={},
        adapter_yaml={"engine_slots": {"swarm/kimi": 5}},
    )
    assert cfg.engine_slots == {"swarm/kimi": 5}
