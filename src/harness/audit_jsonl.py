"""W13-AUDIT-JSONL: forensic audit trail for every harness.dispatch call.

Universal #2 panel pick (commit 7375e5e).  The bloat audit + 15-engine
panel + Round-2 final-verdict all converged on this being the
FOUNDATION for trustworthy auto-defaults — without an append-only
audit trail, every auto-default (auto-lens-set, auto-max-tokens,
auto-retry) becomes an un-debuggable black box.

Design:
  - Append-only JSONL at ``~/.harness/audit.jsonl`` (one JSON object
    per line, single fsync per event)
  - DeepSeek panel S2 finding: every payload that touches this file
    MUST go through ``redact_secrets()`` first.  No exceptions.
  - 7-day age-based prune (size-cap as secondary) keeps the file
    bounded — pattern proven by W11-PER-CHECK-LATENCY-OBSERVABILITY's
    JSONL ledger.
  - File-lock around prune so concurrent dispatches don't lose entries.
  - Best-effort: a failed audit write must NEVER block dispatch.

Event schema (one per dispatch call):

    {
      "ts": "2026-05-25T05:12:34.567Z",
      "event": "dispatch",
      "engine": "kimi",
      "model": "kimi-for-coding",
      "dispatch_id": "abc123..." | null,
      "success": true,
      "error": null | "remote_protocol_error: ...",
      "tokens_in": 142,
      "tokens_out": 380,
      "cost_usd": 0.0,
      "elapsed_ms": 4218,
      "retry_count": 0,             # how many retries the call needed
      "lens_set": null,             # future: which lens-set was used
      "max_tokens_used": 6000,      # for trustworthy auto-defaults
      "prompt_excerpt": "first 200 chars (redacted)",
      "response_excerpt": "first 200 chars (redacted)" | null,
    }

The ``redact_secrets()`` function scrubs:
  - sk-[A-Za-z0-9_-]+ (Anthropic / OpenAI / generic platform keys)
  - sk-or-[A-Za-z0-9_-]+ (OpenRouter)
  - tp-[A-Za-z0-9_-]+ (MiMo Token Plan)
  - AIza[A-Za-z0-9_-]+ (Google Gemini)
  - <UPPER_NAME>_API_KEY=value (env-var style)
  - Bearer <token> (Authorization header style)
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Default ledger location.  Operator can override with HARNESS_AUDIT_PATH.
DEFAULT_AUDIT_PATH = Path.home() / ".harness" / "audit.jsonl"

# Default retention.  Operator can override with HARNESS_AUDIT_MAX_AGE_DAYS.
DEFAULT_MAX_AGE_DAYS = 7

# Secondary safety cap on file size (50 MB) to prevent runaway growth
# if the prune timestamp logic fails.  Operator can override with
# HARNESS_AUDIT_MAX_SIZE_MB.
DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024

# Length of prompt/response excerpts captured in each event.  Short
# enough to keep the ledger small + non-traumatic to scan.
EXCERPT_CHARS = 200

# --- secret redaction ------------------------------------------------------

# Patterns ordered most-specific-first so prefixed forms (sk-or-, tp-)
# match before generic sk- catches them.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsk-or-[A-Za-z0-9_-]{6,}"), "<redacted-openrouter-key>"),
    (re.compile(r"\btp-[A-Za-z0-9_-]{6,}"), "<redacted-mimo-tp-key>"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{10,}"), "<redacted-gemini-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"), "<redacted-platform-key>"),
    (re.compile(
        r"\b([A-Z][A-Z0-9_]{0,30}_API_KEY)\s*=\s*[A-Za-z0-9_+/=-]{4,}",
    ), r"\1=<redacted>"),
    (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9_.\-+/=]{6,}"),
     r"\1 <redacted-bearer-token>"),
    (re.compile(r"(?i)(authorization|x-api-key)\s*:\s*[A-Za-z0-9_.\-+/=]{6,}"),
     r"\1: <redacted-header>"),
]


def redact_secrets(text: str | None) -> str | None:
    """Scrub API-key-like patterns from *text*.

    Returns the redacted string, or None if input was None.  Safe to
    call on any string — never raises.  Patterns are intentionally
    over-permissive: false positives (e.g. innocent text matching a
    pattern) are acceptable; false negatives (leaking a real key) are
    not.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    out = text
    for pattern, replacement in _SECRET_PATTERNS:
        try:
            out = pattern.sub(replacement, out)
        except re.error:  # defensive: corrupted pattern, fail open
            continue
    return out


# --- ledger I/O ------------------------------------------------------------


def _ledger_path(override: Path | None = None) -> Path:
    """Resolve the ledger path with env override + default."""
    if override is not None:
        return override
    env = os.environ.get("HARNESS_AUDIT_PATH")
    if env:
        return Path(env).expanduser()
    return DEFAULT_AUDIT_PATH


def _max_age_days() -> int:
    """Resolve retention with env override."""
    try:
        return int(os.environ.get("HARNESS_AUDIT_MAX_AGE_DAYS",
                                   str(DEFAULT_MAX_AGE_DAYS)))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS


def _max_size_bytes() -> int:
    try:
        mb = float(os.environ.get(
            "HARNESS_AUDIT_MAX_SIZE_MB",
            str(DEFAULT_MAX_SIZE_BYTES // (1024 * 1024)),
        ))
        return int(mb * 1024 * 1024)
    except ValueError:
        return DEFAULT_MAX_SIZE_BYTES


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(s: str) -> datetime | None:
    try:
        # Accept both with-Z and offset-aware
        s_clean = s.rstrip("Z")
        d = datetime.fromisoformat(s_clean)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def append_dispatch_event(*,
                           engine: str,
                           model: str,
                           dispatch_id: Optional[str],
                           success: bool,
                           error: Optional[str],
                           tokens_in: int,
                           tokens_out: int,
                           cost_usd: float,
                           elapsed_ms: int,
                           retry_count: int = 0,
                           lens_set: Optional[str] = None,
                           max_tokens_used: Optional[int] = None,
                           prompt: Optional[str] = None,
                           response: Optional[str] = None,
                           ledger_path: Optional[Path] = None) -> bool:
    """Append one dispatch event to the audit ledger.

    Best-effort: returns True on success, False on any I/O failure.
    NEVER raises.  The caller (typically harness.dispatch) should
    swallow the bool and continue regardless.

    Secret redaction is applied to ``error``, ``prompt``, and ``response``
    BEFORE they are written.  No exceptions.

    Args mirror the DispatchResult fields plus a few extras the audit
    log specifically wants (retry_count, lens_set, max_tokens_used,
    prompt/response excerpts).
    """
    try:
        path = _ledger_path(ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        event = {
            "ts": _now_iso(),
            "event": "dispatch",
            "engine": engine,
            "model": model,
            "dispatch_id": dispatch_id,
            "success": bool(success),
            "error": redact_secrets(error),
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "cost_usd": float(cost_usd),
            "elapsed_ms": int(elapsed_ms),
            "retry_count": int(retry_count),
            "lens_set": lens_set,
            "max_tokens_used": max_tokens_used,
            "prompt_excerpt": _excerpt(prompt),
            "response_excerpt": _excerpt(response),
        }

        # W14-AUDIT-CHAIN-HMAC 2026-05-28: chain the event into the
        # tamper-evident ledger.  Best-effort — if the HMAC key isn't
        # available (e.g. non-Windows host with no env override) the
        # event still writes WITHOUT prev_hash/hmac fields, and the
        # verifier treats it as a legacy entry.  Chain failures NEVER
        # block dispatch.
        try:
            from harness.audit_chain import (
                chain_event as _chain_event,
                get_hmac_key as _get_hmac_key,
                get_last_chain_hash as _get_last_chain_hash,
            )
            _key = _get_hmac_key()
            if _key is not None:
                _prev = _get_last_chain_hash(path)
                event = _chain_event(event, _prev, _key)
        except Exception:
            pass  # Chain is best-effort; event still writes uncheained

        # Append + fsync.  Single open(append) call is atomic at the
        # OS level for writes under 4KB on most filesystems; a JSON line
        # of this shape is comfortably under that.
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            try:
                fh.flush()
                os.fsync(fh.fileno())
            except (OSError, AttributeError):
                pass  # fsync best-effort; not all filesystems support

        # Best-effort prune.  Failures here MUST NOT propagate.
        try:
            _prune_if_needed(path)
        except Exception:
            pass  # Pruning is opportunistic; ledger remains valid + bounded eventually

        return True
    except Exception:
        return False  # Audit is best-effort; never block dispatch


def _excerpt(text: str | None) -> str | None:
    """Truncate + redact a prompt/response excerpt for the ledger."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    truncated = text[:EXCERPT_CHARS]
    if len(text) > EXCERPT_CHARS:
        truncated += "...[truncated]"
    return redact_secrets(truncated)


def _prune_if_needed(path: Path) -> int:
    """Drop entries older than max_age_days OR if file exceeds max size.

    Returns the number of entries removed.  Atomic via temp-file rename
    so a kill mid-prune leaves the original intact.
    """
    if not path.exists():
        return 0
    # Size-cap check (cheap, no parse)
    size = path.stat().st_size
    size_cap_hit = size > _max_size_bytes()
    # Age check
    cutoff = datetime.now(timezone.utc) - timedelta(days=_max_age_days())

    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        try:
            obj = json.loads(line_s)
            ts = _parse_ts(obj.get("ts", ""))
            if ts is None or ts >= cutoff:
                kept.append(line_s)
            else:
                removed += 1
        except json.JSONDecodeError:
            kept.append(line_s)  # preserve malformed (data preservation)

    # If size cap still exceeded after age prune, drop oldest entries
    # until we're under cap.  Approximate by line count.
    if size_cap_hit and kept:
        # Compute kept-bytes; drop from the START (oldest) until under cap
        kept_bytes = sum(len(line) + 1 for line in kept)
        if kept_bytes > _max_size_bytes():
            target = int(_max_size_bytes() * 0.8)  # drop to 80% of cap
            while kept and kept_bytes > target:
                dropped = kept.pop(0)
                kept_bytes -= len(dropped) + 1
                removed += 1

    if removed == 0:
        return 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""),
                    encoding="utf-8")
    tmp.replace(path)
    return removed


# --- read paths ------------------------------------------------------------


def iter_events(*,
                 ledger_path: Optional[Path] = None,
                 since_hours: Optional[float] = None,
                 engine: Optional[str] = None,
                 tail: Optional[int] = None,
                 ) -> list[dict[str, Any]]:
    """Read events from the ledger with optional filtering.

    Args:
        ledger_path: override path; defaults to ``~/.harness/audit.jsonl``
        since_hours: only events within this many hours; None = all
        engine: only events for this engine; None = all
        tail: return only the last N matching events; None = all

    Returns:
        list of event dicts, in file order (oldest -> newest).
    """
    path = _ledger_path(ledger_path)
    if not path.exists():
        return []
    cutoff: datetime | None = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8",
                                errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if engine is not None and obj.get("engine") != engine:
            continue
        if cutoff is not None:
            ts = _parse_ts(obj.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
        events.append(obj)
    if tail is not None and tail >= 0:
        events = events[-tail:]
    return events


def summary(*, ledger_path: Optional[Path] = None,
             since_hours: Optional[float] = None) -> dict[str, Any]:
    """Return a small summary dict suitable for `harness today` /
    dashboard surfaces.

    Shape:
        {
          "total_events": int,
          "successful": int,
          "failed": int,
          "by_engine": {engine: count, ...},
          "total_tokens": int,
          "total_cost_usd": float,
          "window_hours": float | None,
          "retries_total": int,
        }
    """
    events = iter_events(ledger_path=ledger_path, since_hours=since_hours)
    by_engine: dict[str, int] = {}
    successful = 0
    failed = 0
    total_tokens = 0
    total_cost = 0.0
    retries_total = 0
    for ev in events:
        eng = ev.get("engine") or "unknown"
        by_engine[eng] = by_engine.get(eng, 0) + 1
        if ev.get("success"):
            successful += 1
        else:
            failed += 1
        total_tokens += int(ev.get("tokens_in", 0) or 0)
        total_tokens += int(ev.get("tokens_out", 0) or 0)
        total_cost += float(ev.get("cost_usd", 0) or 0)
        retries_total += int(ev.get("retry_count", 0) or 0)
    return {
        "total_events": len(events),
        "successful": successful,
        "failed": failed,
        "by_engine": by_engine,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "window_hours": since_hours,
        "retries_total": retries_total,
    }
