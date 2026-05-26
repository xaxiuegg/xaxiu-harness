"""W14-KEYS-POOL-TIER2 2026-05-26: per-key health tracking.

Where Tier 1 introduced the multi-key resolver + UI, Tier 2 makes
dispatch actually exploit the pool.  This module records the
success/failure outcome of each dispatch against a specific
(provider, slot) pair so that selection can avoid recently-failed
keys.

Storage
=======

JSONL ledger at ``coord/key_health.jsonl`` (one record per dispatch
or probe outcome).  The newest record for each (env_prefix, alias)
wins.  We keep history rather than just current state so the
operator can audit + the ledger seeds the dashboard's per-key panel.

Each record::

    {
      "ts": "2026-05-26T14:32:11.000Z",
      "env_prefix": "KIMI_API_KEY",
      "alias": "k2",
      "env_var": "KIMI_API_KEY_2",
      "category": "up" | "auth-failed" | "quota-exceeded"
                | "transient" | "endpoint-down" | "terminated"
                | "unknown-failure",
      "source": "probe" | "dispatch",
      "details": "optional free-text"
    }

Selection
=========

A key is considered ``unhealthy`` when its most-recent record is in
the set {auth-failed, quota-exceeded, terminated} AND was logged
within the past ``_UNHEALTHY_WINDOW_HOURS`` hours.  ``transient``
and ``endpoint-down`` decay faster (``_TRANSIENT_WINDOW_MINUTES``)
so a brief flap doesn't quarantine the key.

``is_alias_healthy(prefix, alias)`` returns the boolean.
``unhealthy_aliases(prefix)`` returns the set of aliases to exclude.
``pick_next_key`` consults this when ``honor_health=True`` (default).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Optional

logger = logging.getLogger(__name__)


# Categories that quarantine a key for a long window
_PERSISTENT_FAIL_CATEGORIES: frozenset[str] = frozenset({
    "auth-failed",
    "quota-exceeded",
    "terminated",
})
# Categories that are short-lived transient failures
_TRANSIENT_FAIL_CATEGORIES: frozenset[str] = frozenset({
    "transient",
    "endpoint-down",
    "unknown-failure",
})
# Healthy if the latest record is one of these (or in TRANSIENT but
# beyond the transient window, or in PERSISTENT but beyond the
# unhealthy window)
_HEALTHY_CATEGORIES: frozenset[str] = frozenset({"up"})

_UNHEALTHY_WINDOW_HOURS: Final[int] = 24
_TRANSIENT_WINDOW_MINUTES: Final[int] = 30


def _ledger_path() -> Path:
    """Return the canonical ledger path, anchored to repo root."""
    try:
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "coord" / "key_health.jsonl"
    except (IndexError, OSError):
        return Path("coord/key_health.jsonl")


_write_lock = threading.Lock()


@dataclass(frozen=True)
class HealthRecord:
    ts: datetime
    env_prefix: str
    alias: str
    env_var: str
    category: str
    source: str
    details: str = ""

    @classmethod
    def from_dict(cls, row: dict) -> "HealthRecord":
        ts_str = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
        return cls(
            ts=ts,
            env_prefix=row.get("env_prefix", ""),
            alias=row.get("alias", ""),
            env_var=row.get("env_var", ""),
            category=row.get("category", "unknown-failure"),
            source=row.get("source", "dispatch"),
            details=row.get("details", ""),
        )


def record_outcome(
    env_prefix: str,
    alias: str,
    env_var: str,
    category: str,
    *,
    source: str = "dispatch",
    details: str = "",
) -> None:
    """Append a health record to the ledger.  Thread-safe + cross-process.

    W14-KEYS-POOL-HARDENING 2026-05-26: now uses file-lock for
    cross-process safety on Windows + POSIX (panel-audit finding;
    convergent risk flagged by Kimi + DeepSeek).  Within a single
    process the existing threading.Lock still guards.  Across
    processes, the sentinel-file lock prevents interleaved appends.

    Never raises; logs a warning if the write fails.  Callers
    (dispatcher, probe loop) shouldn't crash because of telemetry.
    """
    if not env_prefix or not alias:
        return
    rec = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "env_prefix": env_prefix,
        "alias": alias,
        "env_var": env_var,
        "category": category,
        "source": source,
        "details": details[:500],  # cap to avoid runaway records
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    path = _ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        from harness.keys._lock import file_lock, lock_path_for
        with _write_lock:
            with file_lock(lock_path_for(path)):
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
    except OSError as exc:
        logger.warning(
            "keys.health: ledger write failed (%s); record dropped",
            exc,
        )


def _read_records(path: Optional[Path] = None) -> list[HealthRecord]:
    """Return all records from the ledger.  Empty if file missing."""
    p = path or _ledger_path()
    if not p.exists():
        return []
    out: list[HealthRecord] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(HealthRecord.from_dict(row))
    except OSError:
        return []
    return out


def latest_per_alias(
    env_prefix: str, *, path: Optional[Path] = None,
) -> dict[str, HealthRecord]:
    """Return ``{alias: HealthRecord}`` — the newest record per alias.

    Only records for ``env_prefix`` are considered.
    """
    out: dict[str, HealthRecord] = {}
    for rec in _read_records(path):
        if rec.env_prefix != env_prefix:
            continue
        prior = out.get(rec.alias)
        if prior is None or rec.ts > prior.ts:
            out[rec.alias] = rec
    return out


def is_alias_healthy(
    env_prefix: str,
    alias: str,
    *,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """True iff the alias is currently considered healthy.

    Decision rules:
      - No record at all → True (innocent until proven guilty)
      - Latest is "up" → True
      - Latest is persistent-fail within 24h → False
      - Latest is transient-fail within 30 min → False
      - Latest is fail but past its decay window → True (forgiven)
    """
    latest = latest_per_alias(env_prefix, path=path).get(alias)
    if latest is None:
        return True  # never observed → assume healthy
    if latest.category in _HEALTHY_CATEGORIES:
        return True
    n = now or datetime.now(timezone.utc)
    if latest.ts.tzinfo is None:
        # Defensive: treat naive timestamps as UTC
        latest_ts = latest.ts.replace(tzinfo=timezone.utc)
    else:
        latest_ts = latest.ts
    elapsed = n - latest_ts
    if latest.category in _PERSISTENT_FAIL_CATEGORIES:
        return elapsed > timedelta(hours=_UNHEALTHY_WINDOW_HOURS)
    if latest.category in _TRANSIENT_FAIL_CATEGORIES:
        return elapsed > timedelta(minutes=_TRANSIENT_WINDOW_MINUTES)
    # Unknown category — be conservative + count as healthy after 1h
    return elapsed > timedelta(hours=1)


def unhealthy_aliases(
    env_prefix: str,
    *,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> set[str]:
    """Return the set of currently-unhealthy aliases for ``env_prefix``."""
    return {
        alias for alias in latest_per_alias(env_prefix, path=path)
        if not is_alias_healthy(
            env_prefix, alias, path=path, now=now,
        )
    }


def alias_status_summary(
    env_prefix: str, *, path: Optional[Path] = None,
) -> dict[str, dict]:
    """Per-alias summary for the UI / keys list / probe-all output.

    Returns ``{alias: {category, ts, source, details, healthy}}``.
    """
    out: dict[str, dict] = {}
    for alias, rec in latest_per_alias(env_prefix, path=path).items():
        out[alias] = {
            "category": rec.category,
            "ts": rec.ts.isoformat().replace("+00:00", "Z"),
            "source": rec.source,
            "details": rec.details,
            "healthy": is_alias_healthy(env_prefix, alias, path=path),
        }
    return out


def reset_alias_history(
    env_prefix: str, alias: str, *, path: Optional[Path] = None,
) -> int:
    """Remove all history for a specific (prefix, alias).  Returns the
    number of records dropped.  Used by ``harness keys forget`` and
    by tests.  Atomic — rewrites the file via tmp+replace under lock.
    """
    p = path or _ledger_path()
    if not p.exists():
        return 0
    from harness.keys._lock import file_lock, lock_path_for
    kept = []
    dropped = 0
    try:
        with _write_lock:
            with file_lock(lock_path_for(p)):
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (row.get("env_prefix") == env_prefix
                            and row.get("alias") == alias):
                        dropped += 1
                        continue
                    kept.append(line)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(
                    "\n".join(kept) + ("\n" if kept else ""),
                    encoding="utf-8",
                )
                tmp.replace(p)
    except OSError as exc:
        logger.warning(
            "keys.health: reset_alias_history rewrite failed (%s)", exc,
        )
        return 0
    return dropped


def prune_old_records(
    *,
    keep_per_alias: int = 50,
    path: Optional[Path] = None,
) -> dict:
    """Keep only the newest ``keep_per_alias`` records per
    (env_prefix, alias).  Atomic rewrite under lock.

    Returns a dict with ``{"before": N, "after": N, "dropped": N,
    "aliases_seen": K}``.  Used by ``harness keys health prune`` and
    auto-invoked by ``harness keys probe-all``.

    W14-KEYS-POOL-HARDENING 2026-05-26: addresses the audit-panel
    finding (both Kimi + DeepSeek) that the JSONL ledger grows
    unbounded.  At daily probe-all cadence with 5 keys that's
    ~1800 records/year — modest.  But CI/cron-driven probes can
    accumulate hundreds of records/day; pruning prevents
    monotonic disk growth.
    """
    p = path or _ledger_path()
    if not p.exists():
        return {"before": 0, "after": 0, "dropped": 0, "aliases_seen": 0}

    from harness.keys._lock import file_lock, lock_path_for
    summary = {"before": 0, "after": 0, "dropped": 0, "aliases_seen": 0}
    try:
        with _write_lock:
            with file_lock(lock_path_for(p)):
                # Read + parse all records
                lines = p.read_text(encoding="utf-8").splitlines()
                records: list[tuple[str, dict]] = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    records.append((line, row))
                summary["before"] = len(records)

                # Group by (prefix, alias); newest last
                by_key: dict[tuple[str, str], list[tuple[str, dict]]] = {}
                for raw, row in records:
                    key = (
                        row.get("env_prefix", ""),
                        row.get("alias", ""),
                    )
                    by_key.setdefault(key, []).append((raw, row))
                summary["aliases_seen"] = len(by_key)

                # Trim each group to last N (preserving file order
                # within the group)
                kept_records: list[str] = []
                for key, group in by_key.items():
                    trimmed = group[-keep_per_alias:]
                    kept_records.extend(line for line, _ in trimmed)
                summary["after"] = len(kept_records)
                summary["dropped"] = (
                    summary["before"] - summary["after"]
                )

                # Atomic write under the same lock
                tmp = p.with_suffix(".tmp")
                tmp.write_text(
                    "\n".join(kept_records)
                    + ("\n" if kept_records else ""),
                    encoding="utf-8",
                )
                tmp.replace(p)
    except OSError as exc:
        logger.warning("keys.health: prune failed (%s)", exc)
    return summary
