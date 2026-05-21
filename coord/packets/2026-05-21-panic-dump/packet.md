# PANIC-DUMP — `harness panic-dump` single-command state snapshot

## Goal

Non-technical operator hits "everything is broken".  They need to send
Claude a snapshot of harness state without learning where each piece
lives (history.db, observer/, STATUS.csv, proxy state, harness.log, …).

Single command produces ONE tarball, secret-scrubbed, that the operator
can drop into a chat.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/panic.py`

```python
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


# Patterns that look like leaked API keys / tokens.  Conservative.
_SECRET_RES: list[tuple[str, "re.Pattern[str]"]] = [
    ("api_key_value", re.compile(r"(sk-[A-Za-z0-9_\-]{20,})")),
    ("bearer_token", re.compile(r"(Bearer\s+[A-Za-z0-9._\-]{20,})", re.IGNORECASE)),
    ("env_value_KEY", re.compile(r"((?:KIMI|DEEPSEEK|ANTHROPIC|GEMINI|MOONSHOT|OPENAI)_API_KEY\s*[:=]\s*['\"]?)([^\s'\"]+)")),
]


def _scrub_text(text: str) -> str:
    """Redact common secret patterns in *text*."""
    for _name, pat in _SECRET_RES:
        # The env-value pattern has 2 groups; replace just the value
        if pat.groups == 2:
            text = pat.sub(lambda m: m.group(1) + "<REDACTED>", text)
        else:
            text = pat.sub("<REDACTED>", text)
    return text


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
```

### 2. CLI verb — top-level

In `src/harness/cli.py` find a top-level command (e.g.
`@cli.command(name="doctor")` which was added earlier).  Add a NEW
top-level command:

```python
@cli.command(name="panic-dump")
@click.option("--target-dir", default=None, type=click.Path(path_type=Path),
              help="Output dir (defaults to cwd).")
def panic_dump_cmd(target_dir: Path | None) -> None:
    """Capture a secret-scrubbed snapshot of harness state into one tarball."""
    from harness.panic import panic_dump
    p = panic_dump(target_dir=target_dir)
    click.echo(f"panic-dump written: {p}")
    click.echo(f"size: {p.stat().st_size} bytes")
```

### 3. Tests

`tests/test_panic_dump.py`:

```python
"""Tests for PANIC-DUMP."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.panic import panic_dump, _scrub_text


def test_scrub_redacts_sk_keys() -> None:
    s = "key=sk-AAAAAAAAAAAAAAAAAAAAAAAAAA"
    out = _scrub_text(s)
    assert "sk-AAAAA" not in out
    assert "REDACTED" in out


def test_scrub_redacts_bearer_tokens() -> None:
    s = "Authorization: Bearer abcdefghijklmnopqrstuv"
    out = _scrub_text(s)
    assert "REDACTED" in out
    assert "abcdefghij" not in out


def test_scrub_redacts_env_KEY_values() -> None:
    s = "KIMI_API_KEY=secretvaluehere"
    out = _scrub_text(s)
    assert "secretvaluehere" not in out
    assert "KIMI_API_KEY" in out  # name kept, value redacted


def test_panic_dump_creates_tarball(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = panic_dump(target_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".gz"
    assert "panic-" in out.name


def test_panic_dump_skips_missing_files(tmp_path: Path, monkeypatch) -> None:
    """No coord/, no state/, no .harness/ — dump still produces a tarball."""
    monkeypatch.chdir(tmp_path)
    out = panic_dump(target_dir=tmp_path)
    assert out.exists()
    # Open + verify it's a valid gz tarball
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    # git.txt is always emitted (even if git fails)
    assert any("git.txt" in n for n in names) or names == []


def test_panic_dump_includes_status_csv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "STATUS.csv").write_text(
        "ID,Category,Title,Status\nA,Production,t,queued\n", encoding="utf-8")
    out = panic_dump(target_dir=tmp_path)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert any("status.csv" in n for n in names)
        # Confirm content is in there
        member = next(t for t in tar.getmembers() if "status.csv" in t.name)
        content = tar.extractfile(member).read().decode("utf-8")
        assert "A,Production" in content


def test_cli_panic_dump(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["panic-dump", "--target-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "panic-dump written:" in result.output
```

## Acceptance

- `python -m pytest tests/test_panic_dump.py` — green.
- Full suite stays green.
- `harness panic-dump` produces a `panic-<ts>.tar.gz` file with the
  documented contents, secret-scrubbed.

## Constraints

- DO NOT modify any existing module.
- Secret scrubbing must use stdlib `re` only (no external deps).
- `panic_dump` must NEVER raise — best-effort everywhere.
- Tarball must include git rev, STATUS.csv, log tails, proxy + loop
  state, observer escalations, recent run states.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
