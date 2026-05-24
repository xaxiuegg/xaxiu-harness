"""Pydantic schema for STATUS.csv rows."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Status(StrEnum):
    SHIPPED = "shipped"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"
    TODO = "todo"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    PARTIAL = "partial"
    PROPOSED = "proposed"
    PARKED = "parked"
    SPEC_DONE = "spec-done"
    DESIGN_DONE = "design-done"
    PLANNED = "planned"
    # W11 planning workflow lifecycle states (added 2026-05-25):
    # A row is "split" when it was decomposed into multiple child rows
    # (typically labeled `<ID>-CHILDA` and `<ID>-CHILDB`).  The parent row
    # stays in STATUS.csv as a marker / pointer to its children.
    SPLIT = "split"
    # A row is "merged" when it was folded into another row's scope
    # (e.g. W11-CLAUDE-MD-TEMPLATE merged into W11-AGENT-INIT-VERB to
    # avoid two competing templates).  The merged row stays as a
    # historical marker.
    MERGED = "merged"


class StatusRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9][A-Z0-9_/-]*$")
    category: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    status: Status
    owner: str = Field(min_length=1, max_length=80)
    effort: str = Field(default="-", max_length=40)
    updated: str = Field(default="-", pattern=r"^(\d{4}-\d{2}-\d{2}|-)$")
    # Bumped 1000→4000 (2026-05-22) — real-world defect logs from
    # multi-engine battle tests need room for verbatim error tags +
    # commit hashes + verbose diagnostics in a single cell.
    notes: str = Field(default="", max_length=4000)
