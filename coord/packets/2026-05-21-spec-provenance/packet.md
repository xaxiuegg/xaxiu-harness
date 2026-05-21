# SPEC-PROVENANCE-TRAIL — SHA-stamped spec authorship + tamper detection

## Goal

Between the moment a spec is authored and the moment it reaches
`harness coord plan`, the file lives on disk where any other process can
rewrite it.  Add a simple provenance log so an unexpected mid-flight
change is detectable.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/coord/provenance.py`

```python
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
```

### 2. CLI verbs — TOP LEVEL

Add to `src/harness/cli.py` near other top-level commands (NOT under
coord group):

```python
@cli.command(name="spec-register")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
def spec_register_cmd(spec_path: Path) -> None:
    """Register a spec's SHA256 + author into the provenance log."""
    from harness.coord.provenance import register
    entry = register(spec_path)
    click.echo(f"registered: {entry.spec_path}")
    click.echo(f"  sha256:    {entry.sha256[:16]}...")
    click.echo(f"  operator:  {entry.operator}")
    click.echo(f"  commit:    {entry.git_commit}")
    click.echo(f"  at:        {entry.registered_at}")


@cli.command(name="spec-verify")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
def spec_verify_cmd(spec_path: Path) -> None:
    """Verify a spec's on-disk SHA matches its provenance registration."""
    from harness.coord.provenance import verify
    matches, msg = verify(spec_path)
    click.echo(f"{'OK' if matches else 'MISMATCH'}: {msg}")
    sys.exit(0 if matches else 1)
```

### 3. Tests

`tests/test_spec_provenance.py`:

```python
"""Tests for SPEC-PROVENANCE-TRAIL."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.provenance import register, verify, _sha256_of


def _spec(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "spec.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_register_appends_entry(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    entry = register(spec, log_path=log)
    assert entry.sha256 == _sha256_of(spec)
    assert log.exists()
    rows = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["sha256"] == entry.sha256


def test_register_missing_spec_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        register(tmp_path / "nope.md", log_path=tmp_path / "prov.jsonl")


def test_verify_clean_passes(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    matches, msg = verify(spec, log_path=log)
    assert matches is True
    assert msg == "ok"


def test_verify_detects_tamper(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    spec.write_text("# tampered\n", encoding="utf-8")
    matches, msg = verify(spec, log_path=log)
    assert matches is False
    assert "tampered" in msg


def test_verify_no_registration(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    matches, msg = verify(spec, log_path=log)
    assert matches is False


def test_verify_uses_latest_registration(tmp_path: Path) -> None:
    """If a spec is re-registered after edit, verify against the LATEST SHA."""
    spec = _spec(tmp_path, "# v1\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    spec.write_text("# v2\n", encoding="utf-8")
    register(spec, log_path=log)
    matches, msg = verify(spec, log_path=log)
    assert matches is True


def test_cli_spec_register(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        result = runner.invoke(cli, ["spec-register", str(spec)])
    assert result.exit_code == 0, result.output
    assert "registered:" in result.output
    assert "sha256:" in result.output


def test_cli_spec_verify_exits_1_on_mismatch(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# v1\n", encoding="utf-8")
        runner.invoke(cli, ["spec-register", str(spec)])
        spec.write_text("# tampered\n", encoding="utf-8")
        result = runner.invoke(cli, ["spec-verify", str(spec)])
    assert result.exit_code == 1
    assert "MISMATCH" in result.output
```

## Acceptance

- `python -m pytest tests/test_spec_provenance.py` — green.
- Full suite stays green.

## Constraints

- DO NOT modify dispatch_packet / planner / coordinator — the verify
  call sites are operator-initiated for now (a future row can wire
  auto-verify into the dispatch path).
- Stdlib + harness internals only.
- Keep provenance.py under 150 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
