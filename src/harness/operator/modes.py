"""OperatorMode enum + OperatorConfig Pydantic model (Wave 7).

The operator configures the harness once (CLI flag or adapter YAML);
runtime semantics inherit from this config without re-asserting each
session.  See `spec/operator-modes.md` for the full surface.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "OperatorMode",
    "OperatorConfig",
    "DEFAULT_ENGINE_ROUTING",
    "DEFAULT_ENGINE_SLOTS",
]


class OperatorMode(str, Enum):
    """How autonomous the harness loop runs."""

    REVIEW_EACH = "review_each"
    FULL_DEV_AUTHORITY = "full_dev_authority"
    DRY_RUN = "dry_run"


# Default routing keeps creativity/integrate on the in-session Claude
# (judgment work) and developing/testing on swarm/kimi (code work).
DEFAULT_ENGINE_ROUTING: dict[str, str] = {
    "creativity": "claude-in-session",
    "developing": "swarm/kimi",
    "testing": "swarm/kimi",
    "integrating": "claude-in-session",
    "process_improvement": "claude-in-session",
}

# Calibrated from warehouse empirical data 2026-05-20 (see memory
# reference_xaxiu_swarm_concurrency_calibration): production observed
# 6 swarm/kimi workers + 18 concurrent kimi-api dispatches across 3-key
# pool with zero failures. DeepSeek stays at 1 per cost-on-demand posture.
#
# WIRE-MIMO-SLOTS (2026-05-22): MiMo Token Plan flow control is RPM 100 /
# TPM 10M (Xiaomi docs).  At ~50K input tokens per typical worker packet
# that's 200 in-flight workers before RPM bites — way above any realistic
# need.  Capping at 4 keeps us under the rate limit even on bursty waves
# while leaving room for parallel fan-out comparable to swarm/kimi.
DEFAULT_ENGINE_SLOTS: dict[str, int] = {
    "swarm/kimi": 6,
    "swarm/kimi-api": 6,
    "swarm/deepseek": 1,
    "swarm/mimo": 4,
}


class OperatorConfig(BaseModel):
    """Operator-controllable runtime semantics. One source of truth."""

    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)

    mode: OperatorMode = OperatorMode.REVIEW_EACH
    escalation_threshold: Literal["L1", "L2", "L3", "L4", "L5"] = "L5"
    engine_fill: Literal["aggressive", "conservative", "manual"] = "aggressive"
    max_parallel_supervisors: int = Field(default=4, ge=1, le=16)
    explore_on_uncertainty: Literal[
        "dispatch_alternatives", "inline", "ask_operator"
    ] = "dispatch_alternatives"
    observer_cadence_minutes: int = Field(default=60, ge=5, le=1440)
    profile: Literal["technical", "non_technical"] = "technical"
    engine_routing: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_ENGINE_ROUTING))
    engine_slots: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_ENGINE_SLOTS))
    notification_method: Literal["file", "windows_toast", "email"] = "file"
    notification_target: str = "coord/dev_loop/escalations.md"
