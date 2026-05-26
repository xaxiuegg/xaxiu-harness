"""W14-KEYS-POOL 2026-05-26: generic multi-key resolution for any provider.

Re-exports the resolver public surface so callers can write:

    from harness.keys import resolve_keys, list_provider_keys, KeyEntry

instead of digging into the submodule.
"""
from harness.keys.resolve import (
    KeyEntry,
    discover_pool,
    list_provider_keys,
    mask_value,
    pick_next_key,
    resolve_keys,
)

__all__ = [
    "KeyEntry",
    "discover_pool",
    "list_provider_keys",
    "mask_value",
    "pick_next_key",
    "resolve_keys",
]
