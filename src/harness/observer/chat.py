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

    # Pattern 4: premature-stop — agent declares "saturated/done" while the
    # programmatic stop-check says otherwise.  Cross-references
    # `harness session ok-to-stop`: if recent assistant turns use stopping
    # language AND ok_to_stop() returns False, flag HIGH.
    stop_language_re = re.compile(
        r"\b(saturat(?:ed|ion)|natural\s+stopping\s+point|stopping\s+here|"
        r"session\s+complete|natural\s+pause|wrap[- ]?up\s+here|"
        r"call\s+it\s+a\s+(?:checkpoint|session)|final\s+state)\b",
        re.IGNORECASE,
    )
    has_stop_language = any(stop_language_re.search(t) for t in assistant_turns[-5:])
    if has_stop_language:
        try:
            from harness.session.stop_check import ok_to_stop
            ok, reason = ok_to_stop()
        except Exception:
            ok, reason = True, "stop_check unavailable"
        if not ok:
            report.flags.append(ChatFlag(
                severity="HIGH",
                pattern="premature_stop",
                detail=(
                    f"recent assistant turn contains stopping language but "
                    f"`harness session ok-to-stop` says: {reason}"
                ),
            ))

    return report
