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
