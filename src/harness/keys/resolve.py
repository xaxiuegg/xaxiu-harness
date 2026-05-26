"""W14-KEYS-POOL 2026-05-26: generic multi-key resolution.

Background
==========

The v2 proxy (``src/harness/proxy/app.py``) already discovers Kimi
key pools via ``KIMI_API_KEY``, ``KIMI_API_KEY_1`` ... ``KIMI_API_KEY_4``.
But that resolver is Kimi-specific and the Pattern B engines
(``KimiViaClaudeCodeEngine``, ``MimoViaClaudeCodeEngine``,
``DeepSeekViaClaudeCodeEngine``) read singular ``*_API_KEY`` env vars
directly — meaning the multi-key path silently broke when we moved
from swarm to Pattern B.

This module generalizes the resolver to any provider:

  - ``KIMI_API_KEY``         → slot 1 (legacy singular)
  - ``KIMI_API_KEY_1``       → slot 1 (preferred)
  - ``KIMI_API_KEY_2``       → slot 2
  - ``KIMI_API_KEY_3``       → slot 3
  - ...

Lookup precedence per slot:

  1. Environment variable ``<PREFIX>_<n>`` (n >= 1)
  2. DPAPI store under same name (Windows-only credential vault)

Plus a legacy fallback: if NO indexed slots resolved AND the bare
``<PREFIX>`` (no suffix) is set, treat that as slot 1.  Single-key
operators keep working with no rename.

Tier 2 (W14-KEYS-LABELS-HEALTH 2026-05-26) extends this with an
optional ``<PREFIX>_LABEL_<n>`` env var carrying a human label
("primary", "backup-personal", "premium-tier"), surfaced in the
UI + dispatch logs.

Selection strategies
====================

- ``rotation``  — round-robin across all healthy slots (default).
                  Maximizes throughput on rate-limited providers.
- ``priority``  — always try slot 1; fall to slot 2 only on quota
                  or auth failure of higher-priority slots.
- ``failover-only`` — only use slot >= 2 when slot 1 is
                  circuit-broken.  Useful for "personal key with
                  cheap fallback" topology.

The strategies require per-key health state; that's Tier 2.  Tier 1
implements just the resolver + ``rotation`` (no health, no labels).
"""
from __future__ import annotations

import os
import secrets
import threading
from dataclasses import dataclass, field
from typing import Optional

try:
    from harness.secrets.dpapi import decrypt_secret
except (NotImplementedError, ImportError):  # pragma: no cover
    decrypt_secret = None


# Max numbered slots we look at per provider.  Anything beyond this
# is silently ignored.  4 keeps parity with the v2 proxy + leaves
# headroom for operators with regional / personal / shared / backup.
DEFAULT_MAX_SLOTS = 4


@dataclass(frozen=True)
class KeyEntry:
    """A single discovered API key for a provider.

    Attributes
    ----------
    slot
        1-based index within the provider's pool.  Slot 1 is the
        primary key (the one used in single-key mode).
    alias
        "k1" / "k2" / ... — matches the v2 proxy convention so the
        same KeyEntry can be passed into proxy router code.
    env_var
        The actual env var name where this key was found
        (``KIMI_API_KEY`` for slot 1 legacy, ``KIMI_API_KEY_2`` for
        slot 2, etc.).  The UI uses this to address the right input.
    value
        The raw secret.  NEVER logged directly; always use
        ``mask_value(entry.value)`` for display.
    source
        ``"env"`` for environment variable, ``"dpapi"`` for the
        DPAPI store, ``"env-legacy"`` for the bare ``<PREFIX>``
        fallback.
    label
        Optional human label from ``<PREFIX>_LABEL_<n>`` (Tier 2).
        Empty string when unset.
    """
    slot: int
    alias: str
    env_var: str
    value: str
    source: str
    label: str = ""

    @property
    def masked(self) -> str:
        return mask_value(self.value)


def mask_value(value: str) -> str:
    """Return a masked excerpt safe for display (first 4 + last 4)."""
    if not value:
        return ""
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _env_or_dpapi(name: str) -> tuple[str, str]:
    """Return ``(value, source)`` for ``name``.  Empty value when missing.

    Source is ``"env"``, ``"dpapi"``, or ``""``.
    """
    val = os.environ.get(name) or ""
    if val:
        return val, "env"
    if decrypt_secret is not None:
        try:
            dpv = decrypt_secret(name)
        except Exception:
            dpv = None
        if dpv:
            return dpv, "dpapi"
    return "", ""


def discover_pool(
    env_prefix: str,
    *,
    max_slots: int = DEFAULT_MAX_SLOTS,
) -> list[KeyEntry]:
    """Return all discovered keys for ``env_prefix`` in slot order.

    The returned list is sorted by slot ascending.  Empty when no
    keys are configured.

    Parameters
    ----------
    env_prefix
        The provider's env var prefix, e.g. ``"KIMI_API_KEY"``.  No
        trailing underscore.
    max_slots
        Highest slot index to scan.  Defaults to DEFAULT_MAX_SLOTS (4).
    """
    if not env_prefix:
        return []
    entries: list[KeyEntry] = []

    # Pass 1: indexed slots <PREFIX>_1, _2, _3, ...
    for n in range(1, max_slots + 1):
        name = f"{env_prefix}_{n}"
        value, source = _env_or_dpapi(name)
        if value:
            label_name = f"{env_prefix}_LABEL_{n}"
            label = os.environ.get(label_name) or ""
            entries.append(KeyEntry(
                slot=n,
                alias=f"k{n}",
                env_var=name,
                value=value,
                source=source,
                label=label,
            ))

    # Pass 2: legacy singular fallback when no indexed keys found
    if not entries:
        value, source = _env_or_dpapi(env_prefix)
        if value:
            entries.append(KeyEntry(
                slot=1,
                alias="k1",
                env_var=env_prefix,
                value=value,
                # Tag the source so callers can detect legacy mode +
                # nudge the operator to rename to <PREFIX>_1
                source="env-legacy" if source == "env" else source,
                label="",
            ))

    return entries


def list_provider_keys(
    env_prefix: str,
    *,
    max_slots: int = DEFAULT_MAX_SLOTS,
) -> list[dict]:
    """UI-friendly summary of the pool: per-slot status WITHOUT raw values.

    Includes both populated AND empty slots up through the highest
    populated slot (so the UI can render "Add slot N+1" affordances).

    Each entry: ``{slot, alias, env_var, source, masked, has_value,
    label}``.

    Always emits at least slot 1 — even if empty — so the UI shows
    the primary input.
    """
    populated = discover_pool(env_prefix, max_slots=max_slots)
    by_slot = {e.slot: e for e in populated}
    highest = max(by_slot.keys(), default=0)
    # Show all slots 1..highest plus one empty trailing slot so the
    # operator can add another key without clicking "+ Add"
    upper = max(1, highest)
    # If the operator has no keys at all, still show slot 1 empty
    # If keys are populated, show populated + 1 empty for "next"
    show_count = upper if upper >= max_slots else upper + (
        1 if upper >= 1 and any(by_slot.values()) else 0
    )
    show_count = max(show_count, 1)
    show_count = min(show_count, max_slots)

    out = []
    for n in range(1, show_count + 1):
        entry = by_slot.get(n)
        if entry:
            out.append({
                "slot": n,
                "alias": f"k{n}",
                "env_var": entry.env_var,
                "source": entry.source,
                "masked": entry.masked,
                "has_value": True,
                "label": entry.label,
            })
        else:
            # Empty slot.  Use the indexed env var name even for slot 1
            # so operators are pushed toward the canonical pool form.
            # But preserve legacy singular display when slot==1 and the
            # bare env-var is the operator's mental model — actually no,
            # always show indexed for consistency.  Slot 1 with no keys
            # uses the indexed form too (KIMI_API_KEY_1).
            indexed_name = f"{env_prefix}_{n}"
            out.append({
                "slot": n,
                "alias": f"k{n}",
                "env_var": indexed_name,
                "source": "missing",
                "masked": "",
                "has_value": False,
                "label": "",
            })
    return out


# ---------------------------------------------------------------------------
# Selection (rotation strategy, Tier 1)
# ---------------------------------------------------------------------------

# Per-prefix round-robin counters.  Thread-safe.
_rr_lock = threading.Lock()
_rr_counters: dict[str, int] = {}


def resolve_keys(env_prefix: str) -> dict[str, str]:
    """Backward-compat shim matching the v2 proxy's old API.

    Returns ``{"k1": value, "k2": value, ...}``.  Used by
    ``harness.proxy.app.create_app`` and any other v2-era caller.
    """
    return {e.alias: e.value for e in discover_pool(env_prefix)}


def pick_next_key(
    env_prefix: str,
    *,
    strategy: str = "rotation",
    exclude_aliases: Optional[set[str]] = None,
) -> Optional[KeyEntry]:
    """Pick one key from the pool per ``strategy``.

    Returns ``None`` when no eligible keys exist.

    Strategies
    ----------
    rotation
        Round-robin over all populated slots.  Counter is module-level
        and per-prefix; reset by restart.  Thread-safe.
    priority
        Always return slot 1 unless it's in ``exclude_aliases`` —
        then slot 2, and so on.
    failover-only
        Slot 1 always unless excluded; never slots 2+ unless slot 1
        is excluded.
    """
    pool = discover_pool(env_prefix)
    if not pool:
        return None
    exclude = exclude_aliases or set()
    eligible = [e for e in pool if e.alias not in exclude]
    if not eligible:
        return None

    if strategy == "priority" or strategy == "failover-only":
        # Lowest-slot first; both strategies behave the same when
        # caller drives retry by appending failed alias to
        # exclude_aliases on each attempt.  The user-facing
        # distinction matters when Tier 2 health is wired in.
        return eligible[0]

    # rotation (default)
    with _rr_lock:
        idx = _rr_counters.get(env_prefix, 0)
        chosen = eligible[idx % len(eligible)]
        _rr_counters[env_prefix] = idx + 1
    return chosen


def reset_rotation_counter(env_prefix: Optional[str] = None) -> None:
    """Reset the rotation counter.  Test helper; not used in production.

    With ``env_prefix=None``, resets all counters.
    """
    with _rr_lock:
        if env_prefix is None:
            _rr_counters.clear()
        else:
            _rr_counters.pop(env_prefix, None)
