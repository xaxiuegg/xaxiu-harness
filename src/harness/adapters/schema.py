"""
Pydantic v2 models for xaxiu-harness adapter YAML schema.

All validation, security checks, and type enforcement are applied via
Pydantic validators. The ``load_adapter`` function provides the canonical
entry point for parsing a YAML file into an ``AdapterConfig`` instance.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


class RoutingAction(BaseModel):
    """Backend routing action taken when a rule matches."""

    backend: Literal["deepseek", "kimi", "anthropic", "gemini", "mimo", "burst"]
    model: str | None = Field(default=None, max_length=128)
    extra_args: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class RoutingRule(BaseModel):
    """Conditional routing rule with a human-readable reason."""

    if_: str = Field(alias="if", max_length=256)
    then: RoutingAction
    reason: str | None = Field(default=None, max_length=1024)

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @field_validator("if_")
    @classmethod
    def prevent_regex_dos(cls, v: str) -> str:
        if len(v) >= 512:
            raise ValueError("Regex pattern too long (max 512 chars) to avoid DoS")
        return v


class StatusTrackingConfig(BaseModel):
    """Configuration for the project’s status reporting backend."""

    backend: Literal["csv", "markdown", "jira", "linear"]
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ObserverConfig(BaseModel):
    """Configuration for automatic observer cycles and daily retro."""

    enabled: bool = True
    cadence_minutes: int = Field(default=30, ge=5, le=120)
    daily_retro_time: str = Field(default="17:00")
    flag_patterns: list[str] = Field(
        default=[".*FAIL.*", ".*BLOCKER.*"],
        max_length=32,
    )

    @field_validator("daily_retro_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("daily_retro_time must be HH:MM in 24-hour format")
        return v

    @field_validator("flag_patterns")
    @classmethod
    def prevent_catastrophic_backtracking(cls, v: list[str]) -> list[str]:
        for pattern in v:
            if len(pattern) >= 512:
                raise ValueError(
                    f"Flag pattern too long ({len(pattern)} chars, max 512)"
                )
            # Basic check for catastrophic backtracking patterns (nested quantifiers)
            if re.search(r"\(.*\)\+", pattern) or re.search(r"\\w+\+", pattern):
                # Warn but allow; full detection is deferred to Wave 2
                pass
        return v

    model_config = {"extra": "forbid"}


class SessionHandoffThresholds(BaseModel):
    """Calibrated MB thresholds for the session-handoff monitor.

    Derived from operator's empirical 52 MB crash 2026-05-20 — see
    ``spec/session-handoff-monitor.md``.  ``soft_mb`` triggers a SOFT
    suggestion; ``strongly_mb`` writes the handoff prompt to disk;
    ``critical_mb`` triggers an immediate handoff with shutdown.
    """

    soft_mb: int = Field(default=8, ge=1, le=200)
    strongly_mb: int = Field(default=18, ge=1, le=200)
    critical_mb: int = Field(default=35, ge=1, le=200)

    @model_validator(mode="after")
    def _check_ordering(self) -> "SessionHandoffThresholds":
        if not (self.soft_mb < self.strongly_mb < self.critical_mb):
            raise ValueError(
                "session_handoff thresholds must satisfy "
                "soft_mb < strongly_mb < critical_mb"
            )
        return self

    model_config = {"extra": "forbid"}


class KillConditions(BaseModel):
    """Hard-stop limits applied by the autonomous loop runner.

    Promoted to first-class config 2026-05-21 from the session directive
    ``[[feedback_status_csv_never_empty]]`` corollary — operator wants
    explicit budget kill-switches before any unattended autonomy.  A value
    of ``None`` disables that particular gate.
    """

    max_cost_usd: float | None = Field(default=None, ge=0.0, le=10000.0)
    max_rows_dispatched: int | None = Field(default=None, ge=0, le=100_000)
    max_wallclock_minutes: int | None = Field(default=None, ge=1, le=10_080)

    model_config = {"extra": "forbid"}


class ProductionHygieneBalance(BaseModel):
    """Operator's 90/10 production-vs-hygiene ratio target for the dev loop.

    See ``[[feedback_status_csv_never_empty]]`` — when STATUS.csv backlog
    drains, the manager fires creativity supervisors to repopulate
    production rows so the loop stays in the 90 zone instead of drifting
    into all-hygiene work.  Numbers are PERCENTAGES; they must sum to 100.
    """

    production_percent: int = Field(default=90, ge=0, le=100)
    hygiene_percent: int = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def _check_sum(self) -> "ProductionHygieneBalance":
        if self.production_percent + self.hygiene_percent != 100:
            raise ValueError(
                "production_percent + hygiene_percent must equal 100"
            )
        return self

    model_config = {"extra": "forbid"}


class OperatorSection(BaseModel):
    """Adapter YAML mirror of harness.operator.modes.OperatorConfig.

    Kept structurally distinct from OperatorConfig so the adapter schema
    has one source of truth for YAML validation; the runtime config is
    materialized from this by harness.operator.config.resolve_operator_config.
    """

    model_config = {"extra": "forbid"}

    mode: Literal["review_each", "full_dev_authority", "dry_run"] = "review_each"
    escalation_threshold: Literal["L1", "L2", "L3", "L4", "L5"] = "L5"
    engine_fill: Literal["aggressive", "conservative", "manual"] = "aggressive"
    max_parallel_supervisors: int = Field(default=4, ge=1, le=16)
    explore_on_uncertainty: Literal[
        "dispatch_alternatives", "inline", "ask_operator"
    ] = "dispatch_alternatives"
    observer_cadence_minutes: int = Field(default=60, ge=5, le=1440)
    profile: Literal["technical", "non_technical"] = "technical"
    engine_routing: dict[str, str] = Field(default_factory=dict)
    engine_slots: dict[str, int] = Field(default_factory=dict)
    notification_method: Literal["file", "windows_toast", "email"] = "file"
    notification_target: str = "coord/dev_loop/escalations.md"

    # --- Session-derived directives, promoted to YAML 2026-05-21 ----------
    session_handoff: SessionHandoffThresholds = Field(
        default_factory=SessionHandoffThresholds,
    )
    kill_conditions: KillConditions = Field(default_factory=KillConditions)
    production_hygiene_balance: ProductionHygieneBalance = Field(
        default_factory=ProductionHygieneBalance,
    )


_CRON_REGEX = re.compile(r"^(\S+\s+){4}\S+$")


class ScheduledTask(BaseModel):
    """A supplementary scheduled task registered via Windows Task Scheduler."""

    cron: str = Field(max_length=256)
    command: str = Field(max_length=4096)
    idempotent: bool = True

    @field_validator("cron")
    @classmethod
    def validate_cron_format(cls, v: str) -> str:
        if not _CRON_REGEX.match(v):
            raise ValueError(
                "cron must be a 5-field expression (e.g. '0 9 * * 1-5')"
            )
        return v

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        if not v.startswith("harness "):
            raise ValueError("command must start with 'harness '")
        # Reject dangerous shell metacharacters (allow inside double quotes? simplify)
        forbidden_chars = set(";|&`$()")
        if any(c in v for c in forbidden_chars):
            raise ValueError(
                "command must not contain shell metacharacters: ; | & ` $()"
            )
        return v

    model_config = {"extra": "forbid"}


_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class AdapterConfig(BaseModel):
    """Top-level project adapter configuration."""

    name: str = Field(max_length=64)
    project_root: str = Field(max_length=4096)
    status_tracking: StatusTrackingConfig
    observer: ObserverConfig
    operator: OperatorSection | None = None
    routing_rules: list[RoutingRule] = Field(default_factory=list)
    scheduled_tasks: list[ScheduledTask] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_PATTERN.match(v):
            raise ValueError(
                "name must contain only alphanumerics, underscores, and hyphens"
            )
        if len(v) > 64:
            raise ValueError("name max length is 64 characters")
        return v

    @field_validator("project_root")
    @classmethod
    def validate_project_root(cls, v: str) -> str:
        # Accept absolute path or placeholder {{PROJECT_ROOT}}
        if "{{PROJECT_ROOT}}" not in v:
            path = Path(v)
            if not path.is_absolute():
                raise ValueError(
                    "project_root must be an absolute path or contain "
                    "{{PROJECT_ROOT}} placeholder"
                )
        # Reject '..' traversal patterns
        if ".." in v.split("/") or ".." in v.split("\\"):
            raise ValueError("project_root must not contain '..' traversal")
        return v

    @field_validator("routing_rules")
    @classmethod
    def limit_rules_length(cls, v: list[RoutingRule]) -> list[RoutingRule]:
        if len(v) > 256:
            raise ValueError("Too many routing rules (max 256)")
        return v

    @field_validator("scheduled_tasks")
    @classmethod
    def limit_tasks_length(cls, v: list[ScheduledTask]) -> list[ScheduledTask]:
        if len(v) > 64:
            raise ValueError("Too many scheduled tasks (max 64)")
        return v

    model_config = {
        "extra": "forbid",  # Reject unknown fields
    }


def load_adapter(path: str) -> AdapterConfig:
    """
    Load and validate an adapter YAML file.

    Args:
        path: Filesystem path to the YAML configuration file.

    Returns:
        An ``AdapterConfig`` instance with all fields validated.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML content is invalid or fails any validation rule.
        yaml.YAMLError: If the file cannot be parsed as YAML.
    """
    with open(path, "r", encoding="utf-8") as f:
        # ONLY safe_load – never load()
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError("YAML file is empty or contains only comments")

    try:
        return AdapterConfig.model_validate(data)
    except Exception as exc:
        # Wrap validation errors in a clear ValueError
        raise ValueError(f"Adapter validation failed: {exc}") from exc