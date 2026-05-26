"""W14-KEYS-POOL-TIER2 2026-05-26: per-provider failover-policy storage.

Each provider has a selection strategy:

  - ``rotation`` (default) — round-robin across healthy keys.  Best
    for rate-limit-bound providers where every key has the same cost.
  - ``priority`` — always try k1; fall through to k2 on failure of
    higher-priority keys.  Best for tiered topologies (premium k1,
    routine k2).
  - ``failover-only`` — k1 unless k1 is unhealthy.  Best for "personal
    key with shared fallback" topology.

Storage: ``.harness/key_policy.json`` (per-machine, not committed).
Read on every dispatch (cheap; tiny file).  Default ``rotation`` for
all providers unless overridden.

CLI:

  harness keys policy get
  harness keys policy set KIMI_API_KEY priority
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


VALID_STRATEGIES: frozenset[str] = frozenset({
    "rotation", "priority", "failover-only",
})
DEFAULT_STRATEGY: Final[str] = "rotation"


def _policy_path() -> Path:
    """Return the canonical policy file path, anchored to repo root."""
    try:
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / ".harness" / "key_policy.json"
    except (IndexError, OSError):
        return Path(".harness/key_policy.json")


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
    p = path or _policy_path()
    p.parent.mkdir(parents=True, exist_ok=True)
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
    unknown strategy."""
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"unknown strategy {strategy!r}; "
            f"must be one of {sorted(VALID_STRATEGIES)}"
        )
    data = _read_all(path)
    data[env_prefix] = strategy
    _write_all(data, path)


def list_strategies(*, path: Path | None = None) -> dict[str, str]:
    """Return the full ``{env_prefix: strategy}`` mapping (with the
    default applied for any prefix not explicitly set; caller should
    add provider defaults if needed)."""
    return _read_all(path)
