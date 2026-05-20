"""Operator-modes config surface for xaxiu-harness (Wave 7).

Surfaces every operator directive (full-dev-authority, L5 escalation,
parallelism, engine fill, etc.) as first-class CLI flags + env vars +
adapter YAML keys with precedence CLI > env > YAML > default.
"""

from harness.operator.modes import (
    DEFAULT_ENGINE_ROUTING,
    DEFAULT_ENGINE_SLOTS,
    OperatorConfig,
    OperatorMode,
)
from harness.operator.config import resolve_operator_config

__all__ = [
    "OperatorMode",
    "OperatorConfig",
    "DEFAULT_ENGINE_ROUTING",
    "DEFAULT_ENGINE_SLOTS",
    "resolve_operator_config",
]
