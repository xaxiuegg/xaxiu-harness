"""Session-handoff monitor — proactive transfer recommendation."""

from __future__ import annotations

from harness.session.bootstrap import generate_master_prompt
from harness.session.monitor import (
    CheckReport,
    ack_handoff,
    arm_crisis_check,
    check,
    crisis_check,
)
from harness.session.recommender import Recommendation, recommend
from harness.session.signals import Signals, collect_signals

__all__ = [
    "Signals",
    "collect_signals",
    "Recommendation",
    "recommend",
    "generate_master_prompt",
    "CheckReport",
    "check",
    "ack_handoff",
    "crisis_check",
    "arm_crisis_check",
]
