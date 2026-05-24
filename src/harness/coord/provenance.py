"""Spec provenance trail — SHA256 + author + commit-hash registration.

Records spec authorship into a single append-only JSONL log at
``coord/spec_provenance.jsonl``.  At dispatch time the dispatcher can
verify the on-disk SHA still matches the registered SHA and refuse to
proceed if they diverged.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROVENANCE_LOG = Path("coord") / "spec_provenance.jsonl"


@dataclass(frozen=True)
class ProvenanceEntry:
    spec_path: str
    sha256: str
    operator: str
    git_commit: str
    registered_at: str


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_operator() -> str:
    """Best-effort: read git user.email, fall back to USERNAME / USER env."""
    try:
        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    # Best-effort: this site catches errors from a telemetry / cleanup / log path and intentionally swallows them to keep the primary operation resilient.
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def _current_git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()[:12]
    # Best-effort: this site catches errors from a telemetry / cleanup / log path and intentionally swallows them to keep the primary operation resilient.
    except Exception:
        pass
    return "no-git"


def register(spec_path: Path, *, log_path: Path | None = None) -> ProvenanceEntry:
    """Compute SHA256 + author + commit and append to the provenance log."""
    spec_path = Path(spec_path)
    if not spec_path.exists():
        raise FileNotFoundError(f"spec not found: {spec_path}")
    entry = ProvenanceEntry(
        spec_path=str(spec_path),
        sha256=_sha256_of(spec_path),
        operator=_current_operator(),
        git_commit=_current_git_commit(),
        registered_at=datetime.now(timezone.utc).isoformat(),
    )
    log = log_path or PROVENANCE_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.__dict__) + "\n")
    return entry


def verify(spec_path: Path, *, log_path: Path | None = None) -> tuple[bool, str]:
    """Return (matches, message).

    matches=True when the most recent registered SHA for *spec_path* equals
    the on-disk SHA.  matches=False with a diagnostic when there's a
    mismatch or no registration was found.
    """
    spec_path = Path(spec_path)
    if not spec_path.exists():
        return False, f"spec not found: {spec_path}"
    log = log_path or PROVENANCE_LOG
    if not log.exists():
        return False, "no provenance log — register the spec first"

    target_key = str(spec_path.resolve()) if spec_path.is_absolute() else str(spec_path)
    last_sha: str | None = None
    try:
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("spec_path") in (str(spec_path), target_key):
                last_sha = data.get("sha256")
    except OSError as exc:
        return False, f"could not read provenance log: {exc}"

    if last_sha is None:
        return False, f"no registration for {spec_path}"
    on_disk = _sha256_of(spec_path)
    if last_sha != on_disk:
        return False, f"spec tampered: registered {last_sha[:12]} vs on-disk {on_disk[:12]}"
    return True, "ok"
