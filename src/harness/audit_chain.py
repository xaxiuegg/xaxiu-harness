"""W14-AUDIT-CHAIN-HMAC: tamper-evident audit ledger via SHA-256 + HMAC chain.

Strategic-panel #1 security pick (0.90/0.95 confidence).  Closes the
audit-integrity gap: without this, any process with write access to
``~/.harness/audit.jsonl`` can rewrite history post-hoc — flip a
``success: true`` to false, change an engine name, edit a redacted
excerpt — and there's no signal it happened.

Design
------

Each event written via :func:`harness.audit_jsonl.append_dispatch_event`
gains two extra fields:

- ``prev_hash``: the previous event's ``hmac`` value (the chain link), or
  the sentinel ``"GENESIS"`` for the very first event.
- ``hmac``: hex HMAC-SHA256 keyed off a DPAPI-stored secret, computed
  over the canonical JSON of the event **excluding the hmac field itself**.

To verify the ledger, walk it line-by-line:

1. Each chained entry's ``prev_hash`` must equal the prior chained
   entry's ``hmac`` (or be a documented chain-restart point).
2. Each chained entry's ``hmac`` must reproduce from its own fields +
   the secret key.

Any mismatch flags tampering — the offender either lacked the HMAC key
(so couldn't forge a valid hmac) or didn't recompute the chain (so
prev_hash points wrong).

Key storage
-----------

Priority order:

1. **Env var** ``HARNESS_AUDIT_HMAC_KEY`` (hex-encoded or raw) — for CI,
   tests, and non-Windows hosts.
2. **DPAPI** secret ``HARNESS_AUDIT_HMAC_KEY`` (Windows only) — the
   default production path.
3. **Auto-generate** ``secrets.token_hex(32)`` + persist via DPAPI on
   first use (Windows only).

On non-Windows hosts without the env var, the chain silently degrades:
events still write, but without ``prev_hash``/``hmac`` fields.  The
verifier reports such entries as "legacy" and skips them rather than
failing the whole ledger.

Failure semantics
-----------------

- Chain failures (key missing, hmac compute exception) NEVER block
  dispatch — same best-effort policy as the existing secret redaction.
- The audit ledger remains valid JSONL even if chain fields are absent.
- The verifier reports chain-restart points (genesis, post-prune,
  legacy-to-chained transitions) and only fails on genuine tampering.

Prune interaction
-----------------

When :func:`harness.audit_jsonl._prune_if_needed` drops oldest entries,
the new first-kept entry's ``prev_hash`` will reference a now-deleted
event's ``hmac``.  The verifier accepts this: the first chained entry
seen after the file start is allowed any ``prev_hash`` (treated as a
chain-restart point).  This is the documented cost of pruning; the
detection scope remains "post-hoc tampering within the surviving
window," not "an attacker who can drop earlier entries."
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

GENESIS_HASH = "GENESIS"
"""Sentinel ``prev_hash`` value for the very first chained event."""

HMAC_KEY_NAME = "HARNESS_AUDIT_HMAC_KEY"
"""Env var name + DPAPI secret name for the chain key (must match)."""

CHAIN_FIELDS = ("prev_hash", "hmac")
"""Fields added by chaining; absent in legacy entries."""


# ---------------------------------------------------------------------------
# canonical encoding (must reproduce byte-for-byte for HMAC validity)
# ---------------------------------------------------------------------------


def canonical_json(obj: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding of *obj* for HMAC computation.

    Sorted keys + tight separators + UTF-8 + no escape of non-ASCII —
    these properties together make the encoding stable across Python
    versions, dict insertion order, and locale.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# HMAC key resolution
# ---------------------------------------------------------------------------


def get_hmac_key(*, auto_generate: bool = True) -> Optional[bytes]:
    """Return the HMAC key, or ``None`` if unavailable.

    Resolution order: env var → DPAPI secret → auto-generate + persist
    (Windows only).  Accepts hex-encoded values (decoded to bytes) or
    raw strings (UTF-8 encoded).

    Args:
        auto_generate: if True (default), generate + persist a new key
            via DPAPI on first use.  Set False in tests where you don't
            want the side effect.

    Returns:
        Bytes key, or None on non-Windows hosts with no env override.
    """
    env = os.environ.get(HMAC_KEY_NAME)
    if env:
        return _decode_hmac_key(env)

    try:
        from harness.secrets.dpapi import decrypt_secret, encrypt_secret
    except (ImportError, NotImplementedError):
        return None

    try:
        existing = decrypt_secret(HMAC_KEY_NAME)
    except NotImplementedError:
        return None  # non-Windows host
    except Exception:
        existing = None

    if existing:
        return _decode_hmac_key(existing)

    if not auto_generate:
        return None

    # First-use: generate 256-bit random key, persist via DPAPI.
    new_key_hex = secrets.token_hex(32)
    try:
        encrypt_secret(HMAC_KEY_NAME, new_key_hex)
    except Exception:
        # If persist fails, the chain still works this run but breaks
        # next session — that's still better than no chain at all.
        pass
    return bytes.fromhex(new_key_hex)


def _decode_hmac_key(value: str) -> bytes:
    """Decode a stored/env key — hex if even-length and hex-only, else UTF-8."""
    s = value.strip()
    if len(s) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in s):
        try:
            return bytes.fromhex(s)
        except ValueError:
            pass
    return s.encode("utf-8")


# ---------------------------------------------------------------------------
# chain operations
# ---------------------------------------------------------------------------


def compute_hmac(event: dict[str, Any], key: bytes) -> str:
    """Return hex HMAC-SHA256 of *event* (excluding the ``hmac`` field).

    The exclusion of ``hmac`` is what lets the verifier reproduce the
    value from the on-disk entry — otherwise it'd be circular.
    """
    payload = {k: v for k, v in event.items() if k != "hmac"}
    return _hmac.new(key, canonical_json(payload), hashlib.sha256).hexdigest()


def chain_event(event: dict[str, Any], prev_hash: str, key: bytes) -> dict[str, Any]:
    """Return a copy of *event* with ``prev_hash`` and ``hmac`` filled in.

    Does not mutate the input.  Order: ``prev_hash`` is inserted first
    so it participates in the HMAC computation.
    """
    chained: dict[str, Any] = dict(event)
    chained["prev_hash"] = prev_hash
    chained["hmac"] = compute_hmac(chained, key)
    return chained


def get_last_chain_hash(ledger_path: Path) -> str:
    """Return the most recent ``hmac`` value in the ledger, or GENESIS.

    Reads the entire file (the ledger is bounded by prune); a future
    optimization could read backwards from EOF for large files.
    """
    if not ledger_path.exists():
        return GENESIS_HASH
    try:
        text = ledger_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return GENESIS_HASH
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        h = obj.get("hmac")
        if isinstance(h, str) and h:
            return h
    return GENESIS_HASH


# ---------------------------------------------------------------------------
# verifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainVerifyResult:
    """Outcome of walking the ledger for tamper detection.

    Attributes:
        ok: True iff no tampering detected.  Legacy entries (no chain
            fields) do not affect ``ok`` — they pass through.
        total: number of JSON-decodable entries seen.
        chained: number of entries with prev_hash + hmac.
        legacy: number of entries without chain fields (pre-W14 or
            written when key was unavailable).
        chain_restarts: positions in the file where the chain restarted
            (line numbers; 1-based).  Expected at file start and after
            any post-prune resumption.
        first_tamper_line: 1-based line number of the first tamper
            detected, or None if ok.
        reason: human-readable explanation of the tamper, or None.
        key_available: whether an HMAC key was loadable.  False ⇒ result
            is advisory only (ok flag still meaningful for chain order
            but hmac values weren't verified).
    """
    ok: bool
    total: int
    chained: int
    legacy: int
    chain_restarts: tuple[int, ...]
    first_tamper_line: Optional[int]
    reason: Optional[str]
    key_available: bool


def verify_chain(ledger_path: Path,
                 key: Optional[bytes] = None,
                 ) -> ChainVerifyResult:
    """Walk *ledger_path* line-by-line, verifying chain + hmac integrity.

    Args:
        ledger_path: path to the audit JSONL ledger.
        key: HMAC key bytes.  If None, resolves via :func:`get_hmac_key`
            with ``auto_generate=False`` (verification is read-only).

    Returns:
        :class:`ChainVerifyResult` describing the outcome.  Empty / missing
        ledgers return ok=True with total=0.
    """
    if key is None:
        key = get_hmac_key(auto_generate=False)

    if not ledger_path.exists():
        return ChainVerifyResult(
            ok=True, total=0, chained=0, legacy=0,
            chain_restarts=(), first_tamper_line=None, reason=None,
            key_available=key is not None,
        )

    try:
        lines = ledger_path.read_text(
            encoding="utf-8", errors="replace",
        ).splitlines()
    except OSError as exc:
        return ChainVerifyResult(
            ok=False, total=0, chained=0, legacy=0,
            chain_restarts=(),
            first_tamper_line=None,
            reason=f"ledger read failed: {exc}",
            key_available=key is not None,
        )

    total = 0
    chained = 0
    legacy = 0
    chain_restarts: list[int] = []
    expected_prev: Optional[str] = None  # None ⇒ next chained entry starts a new chain
    last_was_legacy = True  # Treat file start as if preceded by "legacy" so first chained entry starts a chain

    for idx, line in enumerate(lines, start=1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            # Malformed line — already preserved by the appender's
            # best-effort policy.  Don't fail the whole verification.
            continue
        if not isinstance(obj, dict):
            continue
        total += 1
        prev = obj.get("prev_hash")
        h = obj.get("hmac")

        if prev is None or h is None:
            # Legacy entry — pre-chain or chain-degraded write.
            legacy += 1
            last_was_legacy = True
            expected_prev = None
            continue

        chained += 1

        # Validate HMAC reproduces (only if key is available).
        if key is not None:
            recomputed = compute_hmac(obj, key)
            if not _hmac.compare_digest(recomputed, h):
                return ChainVerifyResult(
                    ok=False, total=total, chained=chained, legacy=legacy,
                    chain_restarts=tuple(chain_restarts),
                    first_tamper_line=idx,
                    reason=(f"hmac mismatch at line {idx}: "
                            f"entry tampered (expected {recomputed[:12]}..., "
                            f"found {h[:12]}...)"),
                    key_available=True,
                )

        # Validate prev_hash links.  First chained entry after a legacy
        # run (including file start) is a chain restart — accept any
        # prev_hash but record the position.
        if last_was_legacy or expected_prev is None:
            chain_restarts.append(idx)
            last_was_legacy = False
        else:
            if prev != expected_prev:
                return ChainVerifyResult(
                    ok=False, total=total, chained=chained, legacy=legacy,
                    chain_restarts=tuple(chain_restarts),
                    first_tamper_line=idx,
                    reason=(f"prev_hash mismatch at line {idx}: "
                            f"expected {expected_prev[:12]}..., "
                            f"found {prev[:12]}..."),
                    key_available=key is not None,
                )

        expected_prev = h

    return ChainVerifyResult(
        ok=True, total=total, chained=chained, legacy=legacy,
        chain_restarts=tuple(chain_restarts),
        first_tamper_line=None, reason=None,
        key_available=key is not None,
    )
