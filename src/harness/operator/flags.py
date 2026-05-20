"""Click decorator factory for operator-mode flags (Wave 7).

Applies the operator-mode flags to any Click command or group.  The
flag values are collected into a dict that's then passed to
``resolve_operator_config(cli_overrides=...)``.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import click

__all__ = ["apply_operator_flags", "OPERATOR_FLAG_NAMES"]

OPERATOR_FLAG_NAMES: tuple[str, ...] = (
    "mode",
    "escalation_threshold",
    "engine_fill",
    "max_parallel_supervisors",
    "explore_on_uncertainty",
    "observer_cadence_minutes",
    "profile",
)


_F = TypeVar("_F", bound=Callable[..., object])


def apply_operator_flags(func: _F) -> _F:
    """Decorator: add the seven operator-mode flags to a Click command.

    Each flag defaults to ``None`` so we can distinguish "not provided"
    (skip in resolver) from "explicitly set to default".  The flags
    are stacked in reverse for the same order at help-render time.
    """
    decorators = [
        click.option(
            "--profile",
            type=click.Choice(["technical", "non_technical"]),
            default=None,
            help="Operator profile (affects packet templates / error verbosity).",
        ),
        click.option(
            "--observer-cadence-minutes",
            type=int,
            default=None,
            help="Cadence for the workflow-audit observer cycle.",
        ),
        click.option(
            "--explore-on-uncertainty",
            type=click.Choice(["dispatch_alternatives", "inline", "ask_operator"]),
            default=None,
            help="What to do when the dev manager is uncertain.",
        ),
        click.option(
            "--max-parallel-supervisors",
            type=int,
            default=None,
            help="Max supervisors that may run in parallel within a tick.",
        ),
        click.option(
            "--engine-fill",
            type=click.Choice(["aggressive", "conservative", "manual"]),
            default=None,
            help="Whether to fill idle Kimi slots with queued work.",
        ),
        click.option(
            "--escalation-threshold",
            type=click.Choice(["L1", "L2", "L3", "L4", "L5"]),
            default=None,
            help="Only escalations at or above this level surface to operator.",
        ),
        click.option(
            "--mode",
            type=click.Choice(["review_each", "full_dev_authority", "dry_run"]),
            default=None,
            help="Operator mode: review_each / full_dev_authority / dry_run.",
        ),
    ]
    for d in decorators:
        func = d(func)
    return func
