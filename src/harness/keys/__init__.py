"""W14-KEYS-POOL 2026-05-26: generic multi-key resolution for any provider.

Re-exports the resolver public surface so callers can write:

    from harness.keys import resolve_keys, list_provider_keys, KeyEntry

instead of digging into the submodule.
"""
from harness.keys.health import (
    HealthRecord,
    alias_status_summary,
    is_alias_healthy,
    latest_per_alias,
    prune_old_records,
    record_outcome,
    reset_alias_history,
    unhealthy_aliases,
)
from harness.keys.policy import (
    DEFAULT_STRATEGY,
    VALID_STRATEGIES,
    get_strategy,
    list_strategies,
    set_strategy,
)
from harness.keys.resolve import (
    KeyEntry,
    discover_pool,
    list_provider_keys,
    mask_value,
    pick_next_key,
    resolve_keys,
)

__all__ = [
    "DEFAULT_STRATEGY",
    "HealthRecord",
    "KeyEntry",
    "VALID_STRATEGIES",
    "alias_status_summary",
    "discover_pool",
    "get_strategy",
    "is_alias_healthy",
    "latest_per_alias",
    "list_provider_keys",
    "list_strategies",
    "prune_old_records",
    "mask_value",
    "pick_next_key",
    "record_outcome",
    "reset_alias_history",
    "resolve_keys",
    "set_strategy",
    "unhealthy_aliases",
]
