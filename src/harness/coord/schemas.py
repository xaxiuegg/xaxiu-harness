"""Pydantic v2 models for coordinator IPC schemas.

Defines the four cross-process JSON contracts (WavePlan, WorkerTask,
WorkerStep, WorkerResult, RunState) plus auxiliary status types.
All models use ``extra="forbid"`` to prevent drift.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunStateLiteral(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    INTEGRATING = "integrating"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class WorkerStateLiteral(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REPLAN = "needs_replan"
    PARTIAL = "partial"


class WorkerStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=64)
    kind: Literal["edit", "create", "delete", "test", "shell"]
    instruction: str = Field(min_length=1, max_length=4000)
    target_files: list[str] = Field(default_factory=list, max_length=20)
    expected_diff_lines: int = Field(ge=0, le=2000)
    required_tests: list[str] = Field(default_factory=list, max_length=10)


class WorkerTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(pattern=r"^worker-\d+$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    read_set: list[str] = Field(default_factory=list, max_length=50)
    write_set: list[str] = Field(default_factory=list, max_length=20)
    test_set: list[str] = Field(default_factory=list, max_length=10)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    steps: list[WorkerStep] = Field(default_factory=list, max_length=15)
    estimated_kimi_minutes: int = Field(ge=1, le=60, default=10)
    max_context_tokens: int = Field(ge=1000, le=100000, default=30000)


class WavePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str = Field(pattern=r"^\d{8}T\d{6}-[a-z0-9]{4}$")
    spec_path: str = Field(min_length=1, max_length=512)
    created_at: str
    planner_engine: Literal["claude", "kimi", "kimi-api", "deepseek", "mock"]
    planner_model: str | None = Field(default=None, max_length=128)
    tasks: list[WorkerTask] = Field(min_length=1, max_length=24)
    integration_strategy: Literal["squash", "merge", "rebase"] = "squash"
    notes: str = Field(default="", max_length=2000)


class TestSummary(BaseModel):
    __test__ = False  # silences PytestCollectionWarning (this is not a test class)
    model_config = ConfigDict(extra="forbid")
    ran: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0, default=0)
    duration_seconds: float = Field(ge=0.0)


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    worker_id: str = Field(pattern=r"^worker-\d+$")
    run_id: str
    state: WorkerStateLiteral
    started_at: str
    finished_at: str | None = None
    steps_completed: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list, max_length=50)
    test_summary: TestSummary
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{7,40}$")
    error_tag: str | None = Field(default=None, max_length=64)
    diagnostic: str = Field(default="", max_length=4000)
    tokens_used: int = Field(ge=0, default=0)
    elapsed_seconds: int = Field(ge=0, default=0)


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str
    state: WorkerStateLiteral
    last_checkpoint_at: str | None = None
    last_step_id: str | None = None
    pid: int | None = None


class IntegratorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["pending", "merging", "testing", "committing", "pushing", "done", "failed"]
    last_action: str = ""
    last_action_at: str | None = None
    commit_sha: str | None = None


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    level: Literal["L1", "L2", "L3", "L4", "L5"]
    tag: str
    raised_at: str
    diagnostic: str = ""
    affected_workers: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str
    spec_path: str
    state: RunStateLiteral
    plan_path: str
    started_at: str
    last_tick_at: str
    workers: dict[str, WorkerStatus] = Field(default_factory=dict)
    integrator_status: IntegratorStatus | None = None
    escalations: list[Escalation] = Field(default_factory=list)
