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


class StatusRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9][A-Z0-9_/-]*$")
    category: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    status: Status
    owner: str = Field(min_length=1, max_length=80)
    effort: str = Field(default="-", max_length=40)
    updated: str = Field(default="-", pattern=r"^(\d{4}-\d{2}-\d{2}|-)$")
    notes: str = Field(default="", max_length=1000)
