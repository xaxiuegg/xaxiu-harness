"""harness panic-dump — single-command state snapshot for debugging.

Collects, secret-scrubs, and tars the operator-facing state so a
non-technical operator can paste one path to Claude.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# W9-REDACTION-INTEGRITY-TEST 2026-05-24: delegate to the shared
# state.redaction module so every output surface scrubs against
# the same ground-truth pattern set.  Local _SECRET_RES retained
# for any callers that introspect it (none in tree today).
from harness.state.redaction import redact as _shared_redact

_SECRET_RES: list[tuple[str, "re.Pattern[str]"]] = []  # kept for compat


def _scrub_text(text: str) -> str:
    """Redact common secret patterns in *text*."""
    out = _shared_redact(text)
    return out if out is not None else ""


def _safe_read(path: Path, max_bytes: int = 100 * 1024) -> bytes:
    """Read up to max_bytes from *path*; return scrubbed bytes."""
    try:
        data = path.read_bytes()
    except OSError:
        return b""
    if len(data) > max_bytes:
        data = b"... (truncated to last " + str(max_bytes).encode() + b" bytes)\n" + data[-max_bytes:]
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return data
    return _scrub_text(text).encode("utf-8")


def _tail_lines(path: Path, n: int = 100) -> bytes:
    """Read last *n* lines of *path*, scrubbed."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4 * 1024 * n))
            tail = f.read()
    except OSError:
        return b""
    lines = tail.splitlines()[-n:]
    text = b"\n".join(lines).decode("utf-8", errors="replace")
    return _scrub_text(text).encode("utf-8")


def _git_status() -> bytes:
    """Capture git status + HEAD; never raises."""
    out: list[str] = []
    for args in (["rev-parse", "HEAD"], ["status", "--short"], ["log", "--oneline", "-10"]):
        try:
            r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
            out.append(f"### git {' '.join(args)}\n{r.stdout}\n")
        except Exception as exc:
            out.append(f"### git {' '.join(args)} — failed: {exc}\n")
    return "\n".join(out).encode("utf-8")


def panic_dump(target_dir: Path | None = None) -> Path:
    """Write a tarball of the current harness state to *target_dir*.

    Returns the tarball path.  Best-effort — missing files are silently
    skipped so a broken installation still produces a useful dump.
    """
    target_dir = target_dir or Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = target_dir / f"panic-{ts}.tar.gz"

    # Each entry: (arcname, bytes_payload, mtime_optional)
    entries: list[tuple[str, bytes]] = []
    entries.append(("git.txt", _git_status()))
    entries.append(("status.csv", _safe_read(Path("coord/STATUS.csv"))))
    entries.append(("observer-cycles-tail.txt",
                    _tail_lines(Path("coord/dev_loop/log.jsonl"))))
    entries.append(("harness-jsonl-log-tail.txt",
                    _tail_lines(Path("state/jsonl_log.jsonl"))))
    entries.append(("budget-ledger.jsonl",
                    _safe_read(Path("coord/dev_loop/budget_ledger.jsonl"))))
    entries.append(("proxy-state.json",
                    _safe_read(Path(".harness/proxy_state.json"))))
    entries.append(("loop-state.json",
                    _safe_read(Path("coord/dev_loop/state.json"))))
    # Observer escalations dir (small files)
    esc_dir = Path("coord/observer/escalations")
    if esc_dir.exists():
        for ef in sorted(esc_dir.glob("*.json"))[:20]:
            entries.append((f"escalations/{ef.name}", _safe_read(ef)))
    # Recent run_state snapshots
    runs_dir = Path("runs")
    if runs_dir.exists():
        for rs in sorted(runs_dir.glob("*/run_state.json"))[-5:]:
            entries.append((f"runs/{rs.parent.name}_run_state.json",
                            _safe_read(rs)))

    with tarfile.open(out_path, "w:gz") as tar:
        for arcname, payload in entries:
            if not payload:
                continue
            info = tarfile.TarInfo(name=arcname)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

    return out_path
