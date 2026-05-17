"""Closed-schema JSONL writer for engine performance logs.

Implements v1.2 HIGH-9 (closed schema + redaction) and LOW-7 (rotation at 100MB).
"""

from __future__ import annotations

import gzip
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from harness._constants import PROJECT_NAME_REGEX, STATE_DIR, SUPPORTED_BACKENDS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FILE_NAME: Final = "engine_performance_log.jsonl"
ROTATION_SIZE_BYTES: Final = 100 * 1024 * 1024  # 100 MB

_ALLOWED_OUTCOMES: Final = frozenset(
    {
        "success",
        "timeout",
        "api_error",
        "packet_trap",
        "fallback",
        "all_fallbacks_exhausted",
    }
)

_ALLOWED_KEYS: Final = frozenset(
    {
        "timestamp",
        "project",
        "packet_path",
        "backend",
        "model",
        "outcome",
        "latency_ms",
        "fallback_to",
    }
)

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_REDACTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"(?i)api[_-]?key\s*[\"':=]+\s*[\"']?[A-Za-z0-9_-]{16,}"),
    re.compile(r"ms-[A-Za-z0-9]{20,}"),
    re.compile(r"deepseek-[A-Za-z0-9]{20,}"),
)


class LogSchemaError(ValueError):
    """Raised when a log record violates the closed schema."""


def _redact(text: str | None) -> str | None:
    """Remove secret-like patterns from *text*, returning the cleaned string.

    Returns ``None`` unchanged so optional fields stay optional.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _log_path() -> Path:
    return Path(STATE_DIR) / LOG_FILE_NAME


def _rotation_suffix() -> str:
    """YYYY-MM formatted string for the current UTC month."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _set_restricted_permissions(path: Path) -> None:
    """Set mode 0600 (owner read/write only) on *path* if possible."""
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def rotate_if_needed() -> None:
    """Rotate the JSONL log if it exceeds 100 MB.

    The rotated file is gzip-compressed and named
    ``engine_performance_log.<YYYY-MM>.jsonl.gz`` in the same directory.
    After rotation the original file is truncated to empty.
    """
    log_file = _log_path()
    if not log_file.exists():
        return

    try:
        size = log_file.stat().st_size
    except OSError:
        return

    if size <= ROTATION_SIZE_BYTES:
        return

    rotated = log_file.with_suffix(f".{_rotation_suffix()}.jsonl.gz")
    # If a rotation already exists for this month, append a counter.
    counter = 1
    while rotated.exists():
        rotated = log_file.with_suffix(f".{_rotation_suffix()}-{counter}.jsonl.gz")
        counter += 1

    # Atomic-ish: read original, write compressed, then truncate.
    try:
        with open(log_file, "rb") as src:
            with gzip.open(rotated, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
        _set_restricted_permissions(rotated)
        # Truncate original.
        with open(log_file, "wb") as f:
            pass
        _set_restricted_permissions(log_file)
    except OSError:
        # If rotation fails, leave the original file intact rather than
        # losing data. The next write will retry.
        return


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_log_entry(
    *,
    project: str,
    packet_path: str,
    backend: str,
    model: str | None,
    outcome: str,
    latency_ms: int,
    fallback_to: str | None,
) -> None:
    """Append a single record to ``state/engine_performance_log.jsonl``.

    Validates the closed schema, redacts secrets, and rotates automatically.
    """
    rotate_if_needed()

    # --- validation ---
    if outcome not in _ALLOWED_OUTCOMES:
        raise ValueError(
            f"outcome={outcome!r} not in allowed set: {sorted(_ALLOWED_OUTCOMES)}"
        )

    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"backend={backend!r} not in supported backends: {sorted(SUPPORTED_BACKENDS)}"
        )

    if not re.fullmatch(PROJECT_NAME_REGEX, project):
        raise ValueError(
            f"project={project!r} does not match PROJECT_NAME_REGEX={PROJECT_NAME_REGEX!r}"
        )

    # --- build record (exactly 8 keys, no looping) ---
    record: dict[str, object] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "packet_path": _redact(packet_path),
        "backend": _redact(backend),
        "model": model,
        "outcome": _redact(outcome),
        "latency_ms": int(latency_ms),
        "fallback_to": _redact(fallback_to),
    }

    if set(record) != _ALLOWED_KEYS:
        raise LogSchemaError(
            f"Record keys {set(record)!r} do not match allowed keys {_ALLOWED_KEYS!r}"
        )

    # --- serialize & atomic append ---
    line = json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
    data = line.encode("utf-8")

    log_file = _log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "ab") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    _set_restricted_permissions(log_file)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_recent_entries(limit: int = 50) -> list[dict]:
    """Return the most recent *limit* entries from the JSONL log.

    Entries are returned newest-first. Defaults to 50.
    """
    limit = max(1, min(int(limit), 1000))
    log_file = _log_path()
    if not log_file.exists():
        return []

    entries: list[dict] = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []

    # Return newest-first.
    return entries[-limit:][::-1]
