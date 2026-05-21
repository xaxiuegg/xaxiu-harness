# CHAT-OBSERVER — meta-audit primitive over session transcript jsonl

## Goal

Add a Chat Observer that periodically reads Claude Code's per-session
transcript jsonl (`~/.claude/projects/<slug>/<uuid>.jsonl`) and flags
dev-manager pattern drift — for example: "." reply loops, long stretches
without commits, missing STATUS.csv updates, or hung dispatches that the
operator should know about.

This is a NEW observer cycle that complements the existing
`harness observer cycle` (which audits the project state).  The Chat
Observer audits the conversation itself.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/observer/chat.py`

```python
"""Chat Observer — audits the session transcript jsonl for dev-manager drift.

This module reads Claude Code's per-session transcript file at
``~/.claude/projects/<cwd-slug>/<latest>.jsonl`` (the same file the
session-handoff monitor watches) and produces an :class:`AuditReport`
listing patterns that the operator should see.

It is intentionally a separate primitive from the project-state observer
(see ``src/harness/observer/cycle.py``) — the existing observer answers
"is the project healthy?", whereas the Chat Observer answers "is the dev
manager (Claude) doing the right things in this conversation?".
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ChatFlag:
    severity: str  # "INFO" | "MED" | "HIGH"
    pattern: str   # short tag, e.g. "dot_reply_loop"
    detail: str    # human-readable description
    sample: str = ""  # short excerpt that triggered the flag


@dataclass
class AuditReport:
    flags: list[ChatFlag] = field(default_factory=list)
    transcript_path: Optional[Path] = None
    line_count: int = 0
    assistant_turn_count: int = 0


def _cwd_slug() -> str:
    """Return the Claude Code projects-dir slug for the current cwd.

    Claude Code maps a project dir to `~/.claude/projects/<slug>/` where
    <slug> is the absolute path with separators replaced by '-' and the
    drive colon removed.  e.g. D:\\Projects\\xaxiu-harness -> D--Projects-xaxiu-harness
    """
    cwd = str(Path.cwd().resolve())
    return cwd.replace(":", "").replace("\\", "-").replace("/", "-")


def _claude_projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _latest_session_jsonl() -> Optional[Path]:
    base = _claude_projects_dir() / _cwd_slug()
    if not base.exists():
        return None
    candidates = sorted(base.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


_DOT_REPLY_RE = re.compile(r"^\s*\.\s*$")


def audit(
    transcript_path: Optional[Path] = None,
    *,
    tail_lines: int = 500,
) -> AuditReport:
    """Read the latest tail of the session transcript and flag drift patterns.

    Detects (current set, extensible):

    1. ``dot_reply_loop`` — 3+ consecutive assistant turns whose text is
       just "." (the Stop-hook silent-loop pattern from
       ``[[feedback_never_silent_on_hook_loops]]``).
    2. ``long_silence_no_commit`` — INFO flag when >50 assistant turns
       since the transcript appears to have produced any git commit text.
    3. ``status_csv_missed`` — MED flag when a "task completed" pattern
       appears in assistant text without a STATUS.csv update mention in
       the same window.
    """
    path = transcript_path or _latest_session_jsonl()
    report = AuditReport(transcript_path=path)
    if path is None or not path.exists():
        return report

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return report
    report.line_count = len(lines)
    tail = lines[-tail_lines:]

    assistant_turns: list[str] = []
    for line in tail:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("role") == "assistant" or row.get("type") == "assistant":
            content = row.get("content") or row.get("text") or ""
            if isinstance(content, list):
                # Claude API content is a list of blocks; concatenate text blocks
                content = "\n".join(
                    str(b.get("text", "")) for b in content if isinstance(b, dict)
                )
            assistant_turns.append(str(content))
    report.assistant_turn_count = len(assistant_turns)

    # Pattern 1: dot-reply loop
    streak = 0
    max_streak = 0
    for text in assistant_turns:
        if any(_DOT_REPLY_RE.match(ln) for ln in text.splitlines()) and len(text.strip()) <= 3:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    if max_streak >= 3:
        report.flags.append(ChatFlag(
            severity="HIGH",
            pattern="dot_reply_loop",
            detail=f"{max_streak} consecutive '.' assistant replies — silent stop-hook loop suspected",
        ))

    # Pattern 2: long silence without commit
    has_commit_text = any(
        "git commit" in t or "[master" in t or "Co-Authored-By" in t
        for t in assistant_turns
    )
    if len(assistant_turns) >= 50 and not has_commit_text:
        report.flags.append(ChatFlag(
            severity="INFO",
            pattern="long_silence_no_commit",
            detail=f"{len(assistant_turns)} assistant turns inspected with no commit text — verify work is being persisted",
        ))

    # Pattern 3: status-csv missed
    completion_window: list[str] = []
    for text in assistant_turns:
        if "completed" in text.lower() or "shipped" in text.lower():
            completion_window.append(text)
    if completion_window:
        sees_csv = any("STATUS.csv" in t for t in completion_window)
        if not sees_csv:
            report.flags.append(ChatFlag(
                severity="MED",
                pattern="status_csv_missed",
                detail="completion/ship language detected without a STATUS.csv update mention",
            ))

    return report
```

### 2. CLI integration

Locate the observer command group in `cli.py` (search for
`@cli.group(name="observer")` or `def observer_group`).  Add a new
subcommand:

```python
@observer_group.command(name="audit-chat")
@click.option("--tail-lines", default=500, type=int,
              help="Number of trailing transcript lines to scan.")
def observer_audit_chat(tail_lines: int) -> None:
    """Audit the Claude Code session transcript for dev-manager drift."""
    from harness.observer.chat import audit
    report = audit(tail_lines=tail_lines)
    if report.transcript_path is None:
        click.echo("error: could not locate session transcript jsonl", err=True)
        sys.exit(1)
    click.echo(f"transcript: {report.transcript_path}")
    click.echo(f"lines: {report.line_count}  assistant_turns: {report.assistant_turn_count}")
    if not report.flags:
        click.echo("flags: none")
        return
    for f in report.flags:
        click.echo(f"  [{f.severity}] {f.pattern}: {f.detail}")
```

### 3. Tests

New file `tests/test_observer_chat.py`:

```python
"""Tests for harness.observer.chat — Chat Observer audit primitive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.observer.chat import audit, _DOT_REPLY_RE


def _write_transcript(path: Path, assistant_texts: list[str]) -> None:
    """Write a fake Claude Code transcript jsonl with the given assistant turns."""
    lines: list[str] = []
    for t in assistant_texts:
        lines.append(json.dumps({"role": "assistant", "content": t}))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_audit_missing_transcript_returns_empty(tmp_path: Path) -> None:
    report = audit(transcript_path=tmp_path / "nope.jsonl")
    assert report.flags == []
    assert report.assistant_turn_count == 0


def test_audit_flags_dot_reply_loop(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_transcript(p, ["regular reply", ".", ".", ".", "back to normal"])
    report = audit(transcript_path=p)
    tags = {f.pattern for f in report.flags}
    assert "dot_reply_loop" in tags
    flag = next(f for f in report.flags if f.pattern == "dot_reply_loop")
    assert flag.severity == "HIGH"


def test_audit_does_not_flag_short_streak(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_transcript(p, [".", ".", "real reply"])
    report = audit(transcript_path=p)
    assert "dot_reply_loop" not in {f.pattern for f in report.flags}


def test_audit_flags_long_silence_no_commit(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_transcript(p, [f"reply {i}" for i in range(60)])
    report = audit(transcript_path=p)
    assert "long_silence_no_commit" in {f.pattern for f in report.flags}


def test_audit_does_not_flag_silence_when_commit_text_present(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    texts = [f"reply {i}" for i in range(59)] + ["[master abc1234] feat: thing"]
    _write_transcript(p, texts)
    report = audit(transcript_path=p)
    assert "long_silence_no_commit" not in {f.pattern for f in report.flags}


def test_audit_flags_status_csv_missed(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_transcript(p, ["wave 3 shipped", "moving on"])
    report = audit(transcript_path=p)
    assert "status_csv_missed" in {f.pattern for f in report.flags}


def test_audit_does_not_flag_status_csv_missed_when_mentioned(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    _write_transcript(p, ["wave 3 shipped; STATUS.csv updated"])
    report = audit(transcript_path=p)
    assert "status_csv_missed" not in {f.pattern for f in report.flags}


def test_dot_reply_regex_matches_whitespace_only_dot() -> None:
    assert _DOT_REPLY_RE.match(".")
    assert _DOT_REPLY_RE.match("  .  ")
    assert not _DOT_REPLY_RE.match("..")
    assert not _DOT_REPLY_RE.match(". foo")
```

## Acceptance

- `python -m pytest tests/test_observer_chat.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- `harness observer audit-chat --help` shows the new command.
- Manual: `harness observer audit-chat --tail-lines 200` runs against the
  real session transcript and prints either "flags: none" or a list.

## Constraints

- Do NOT modify `src/harness/observer/cycle.py` or the existing observer
  flag pipeline.
- Do NOT touch existing tests.
- Keep `chat.py` under 200 LOC.
- Stdlib only.

## Engine guidance

This is one new module + one CLI subcommand + one test file.  Tight scope,
self-contained — swarm/kimi (agentic) or swarm/kimi-api (FIND/REPLACE)
both work.  Timeout 420s.
