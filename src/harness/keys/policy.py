"""W14-KEYS-POOL-TIER2 2026-05-26: per-provider failover-policy storage.

Each provider has a selection strategy:

  - ``rotation`` (default) — round-robin across healthy keys.  Best
    for rate-limit-bound providers where every key has the same cost.
  - ``priority`` — always try k1; fall through to k2 on failure of
    higher-priority keys.  Best for tiered topologies (premium k1,
    routine k2).
  - ``failover-only`` — k1 unless k1 is unhealthy.  Best for "personal
    key with shared fallback" topology.

Storage: ``coord/key_policy.json`` (committable; W14-KEYS-POOL-
HARDENING 2026-05-26 moved from per-machine ``.harness/``).  Read on
every dispatch (cheap; tiny file).  Default ``rotation`` for all
providers unless overridden.

Per-machine override: set ``HARNESS_KEY_POLICY_PATH`` env var to point
at a different file.

CLI:

  harness keys policy get
  harness keys policy set KIMI_API_KEY priority
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


VALID_STRATEGIES: frozenset[str] = frozenset({
    "rotation", "priority", "failover-only",
})
DEFAULT_STRATEGY: Final[str] = "rotation"


def _policy_path() -> Path:
    """Return the canonical policy file path, anchored to repo root.

    W14-KEYS-POOL-HARDENING 2026-05-26: moved from ``.harness/`` (per-
    machine, gitignored) to ``coord/`` (committable) so cross-machine
    setups share the same strategy by default.  Operators that want
    per-machine strategy can set ``HARNESS_KEY_POLICY_PATH`` env var
    to point at a different file.

    Migration: if both ``coord/key_policy.json`` AND the legacy
    ``.harness/key_policy.json`` exist, the legacy file is moved into
    place on first access.  After migration, only the ``coord/`` file
    is read.
    """
    # Env-var override for operators who want per-machine policy
    override = os.environ.get("HARNESS_KEY_POLICY_PATH", "").strip()
    if override:
        return Path(override)
    try:
        repo_root = Path(__file__).resolve().parents[3]
        new_path = repo_root / "coord" / "key_policy.json"
        legacy_path = repo_root / ".harness" / "key_policy.json"
        # One-time migration: if legacy exists and new doesn't, move
        if legacy_path.exists() and not new_path.exists():
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.rename(new_path)
                logger.info(
                    "keys.policy: migrated %s -> %s "
                    "(W14-KEYS-POOL-HARDENING)",
                    legacy_path, new_path,
                )
            except OSError:
                # If migration fails, fall back to legacy path
                return legacy_path
        return new_path
    except (IndexError, OSError):
        return Path("coord/key_policy.json")


def _read_all(path: Path | None = None) -> dict[str, str]:
    p = path or _policy_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if v in VALID_STRATEGIES}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict[str, str], path: Path | None = None) -> None:
    """Atomic write under a sentinel-file lock.  Cross-process safe.

    W14-KEYS-POOL-HARDENING 2026-05-26: addresses the panel-audit
    finding (both Kimi + DeepSeek) that concurrent
    ``harness keys policy set`` invocations would race.
    """
    p = path or _policy_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    from harness.keys._lock import file_lock, lock_path_for
    with file_lock(lock_path_for(p)):
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)


def get_strategy(env_prefix: str, *, path: Path | None = None) -> str:
    """Return the strategy for ``env_prefix``, default ``rotation``."""
    return _read_all(path).get(env_prefix, DEFAULT_STRATEGY)


def set_strategy(
    env_prefix: str, strategy: str, *, path: Path | None = None,
) -> None:
    """Persist the strategy for ``env_prefix``.  Raises ValueError on
    unknown strategy.

    Cross-process safe via file-lock around the read-modify-write.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"unknown strategy {strategy!r}; "
            f"must be one of {sorted(VALID_STRATEGIES)}"
        )
    from harness.keys._lock import file_lock, lock_path_for
    p = path or _policy_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Lock around the read-modify-write to prevent lost updates
    with file_lock(lock_path_for(p)):
        data = _read_all(path)
        data[env_prefix] = strategy
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)


def list_strategies(*, path: Path | None = None) -> dict[str, str]:
    """Return the full ``{env_prefix: strategy}`` mapping (with the
    default applied for any prefix not explicitly set; caller should
    add provider defaults if needed)."""
    return _read_all(path)
