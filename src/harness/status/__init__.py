"""Canonical STATUS tracker primitive for xaxiu-harness."""

from __future__ import annotations

from harness.status.hooks import on_commit, on_dispatch_complete, on_dispatch_start
from harness.status.schema import Status, StatusRow
from harness.status.store import (
    add_row,
    read_status,
    summary,
    update_row,
    verify,
    write_status,
)

__all__ = [
    "Status",
    "StatusRow",
    "read_status",
    "write_status",
    "add_row",
    "update_row",
    "summary",
    "verify",
    "on_dispatch_start",
    "on_dispatch_complete",
    "on_commit",
]
