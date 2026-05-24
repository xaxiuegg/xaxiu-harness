"""W11-DISPATCH-CACHE: content+adapter-hash keyed dispatch cache.

Stores DispatchResult payloads under `.harness/dispatched/` keyed by:

    <content_hash>__<adapter_hash>.json

Cache hit semantics:
  - Same packet content + same adapter content -> cached result returned
  - Packet content changes -> cache miss (different content_hash)
  - Adapter file edits -> cache miss (different adapter_hash)
  - Stored result older than TTL -> cache miss (deleted on read)
  - --no-cache parameter bypasses both read + write

Why content+adapter hash:
  - Pure content hash would cache stale results when the agent
    edits adapter routing rules (engine/model swap) without
    changing the packet.
  - The combined key invalidates BOTH dimensions of "same logical
    dispatch" without needing manual cache invalidation.

TTL semantics:
  - Default 24h via HARNESS_DISPATCH_CACHE_TTL_SEC env var.
  - Expired entries are deleted lazily on next lookup attempt.
  - No background sweep (keeps the module dependency-free).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any


DEFAULT_TTL_SEC = 24 * 60 * 60  # 24h


# -- TTL --


def _ttl_seconds() -> int:
    """Read HARNESS_DISPATCH_CACHE_TTL_SEC env var; default 24h."""
    raw = os.environ.get("HARNESS_DISPATCH_CACHE_TTL_SEC", "")
    if not raw.strip():
        return DEFAULT_TTL_SEC
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_SEC


# -- Hash computation --


def _hash_bytes(data: bytes) -> str:
    """Return a short stable hex hash for *data*."""
    return hashlib.sha256(data).hexdigest()[:16]


def _hash_file(path: Path) -> str:
    """Hash a file's bytes.  Returns empty-hash for missing files
    so the cache key remains well-formed even when the adapter
    hasn't been written yet."""
    try:
        return _hash_bytes(path.read_bytes())
    except OSError:
        return "missing"


def _hash_text(text: str) -> str:
    return _hash_bytes(text.encode("utf-8"))


def compute_cache_key(packet_content: str,
                      adapter_path: Path | str | None) -> str:
    """Compute the cache key for a (packet, adapter) pair.

    Both inputs feed the key so a change to either invalidates
    cached results.  Format: ``<content_hash>__<adapter_hash>``.
    """
    content_hash = _hash_text(packet_content)
    if adapter_path is None:
        adapter_hash = "noadapter"
    else:
        adapter_hash = _hash_file(Path(adapter_path))
    return f"{content_hash}__{adapter_hash}"


# -- Cache directory resolution --


def cache_dir_for(project_root: Path | str | None = None) -> Path:
    """Return the `.harness/dispatched/` cache dir for *project_root*.

    Defaults to cwd / .harness/dispatched/.
    """
    base = Path(project_root) if project_root else Path.cwd()
    return base / ".harness" / "dispatched"


def cache_path_for(cache_key: str,
                   project_root: Path | str | None = None) -> Path:
    return cache_dir_for(project_root) / f"{cache_key}.json"


# -- Read / write --


def lookup(cache_key: str,
           *,
           project_root: Path | str | None = None,
           ttl_sec: int | None = None) -> dict[str, Any] | None:
    """Return cached entry as a dict, or None on miss (incl. expiry).

    Expired entries are deleted lazily.  Corrupted entries (malformed
    JSON) are also deleted so the next dispatch repopulates clean.
    """
    path = cache_path_for(cache_key, project_root)
    if not path.exists():
        return None
    ttl = _ttl_seconds() if ttl_sec is None else ttl_sec
    if ttl > 0:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return None
        if age > ttl:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupted cache entry — drop it
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def store(cache_key: str,
          payload: dict[str, Any] | Any,
          *,
          project_root: Path | str | None = None) -> Path:
    """Write *payload* to the cache directory keyed by *cache_key*.

    Accepts either a plain dict OR a dataclass (auto-converted via
    asdict).  Returns the written path.

    Best-effort: filesystem errors are swallowed (cache is a perf
    optimization, not a correctness primitive).  Returns the would-be
    path even on failure so callers can choose to retry.
    """
    if is_dataclass(payload):
        payload = asdict(payload)
    cdir = cache_dir_for(project_root)
    path = cdir / f"{cache_key}.json"
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        # Atomic write via tmp + rename so a kill mid-write doesn't
        # corrupt the entry.  Uses W9 atomic-write helper if available.
        try:
            from harness.state.files import atomic_write_json
            atomic_write_json(path, payload, set_mode_0600=False)
        except (ImportError, Exception):
            # Best-effort fallback: direct write
            path.write_text(
                json.dumps(payload, default=str), encoding="utf-8",
            )
    except OSError:
        pass
    return path


def invalidate(cache_key: str,
               *,
               project_root: Path | str | None = None) -> bool:
    """Delete a single cache entry.  Returns True if entry existed."""
    path = cache_path_for(cache_key, project_root)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def clear_all(project_root: Path | str | None = None) -> int:
    """Delete every cached entry under the project's .harness/dispatched/.

    Returns count of deleted files.  No-op if the dir doesn't exist.
    """
    cdir = cache_dir_for(project_root)
    if not cdir.is_dir():
        return 0
    count = 0
    for entry in cdir.glob("*.json"):
        try:
            entry.unlink()
            count += 1
        except OSError:
            pass
    return count


# -- Convenience: stats for budget_status / telemetry surfaces ----------


def cache_stats(project_root: Path | str | None = None) -> dict[str, int]:
    """Return basic stats: {entries, total_bytes} for the cache dir."""
    cdir = cache_dir_for(project_root)
    if not cdir.is_dir():
        return {"entries": 0, "total_bytes": 0}
    entries = 0
    total_bytes = 0
    for p in cdir.glob("*.json"):
        try:
            total_bytes += p.stat().st_size
            entries += 1
        except OSError:
            pass
    return {"entries": entries, "total_bytes": total_bytes}
