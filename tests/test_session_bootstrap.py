"""Tests for harness.session.bootstrap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from harness.session.bootstrap import (
    _last_commit,
    _load_state,
    _status_summary_text,
    generate_master_prompt,
)


class TestLoadState:
    def test_missing(self, tmp_path: Path) -> None:
        assert _load_state(tmp_path / "nope.json") == {}

    def test_bad_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert _load_state(p) == {}


class TestLastCommit:
    def test_success(self) -> None:
        with patch("harness.session.bootstrap.subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="abc123 message\n")
            assert _last_commit() == "abc123 message"

    def test_failure(self) -> None:
        with patch("harness.session.bootstrap.subprocess.run") as m:
            m.return_value = MagicMock(returncode=1, stdout="")
            assert _last_commit() == "(unknown)"


class TestStatusSummaryText:
    def test_ok(self, tmp_path: Path) -> None:
        p = tmp_path / "STATUS.csv"
        p.write_text(
            "id,category,title,status,owner,effort,updated,notes\n"
            "1,a,b,todo,me,1,2024-01-01,none\n"
            "2,a,c,shipped,me,1,2024-01-02,none\n"
        )
        text = _status_summary_text(p)
        assert "todo" in text
        assert "shipped" in text

    def test_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "STATUS.csv"
        p.write_text("id,category,title,status,owner,effort,updated,notes\n")
        assert _status_summary_text(p) == "(none)"


class TestGenerateMasterPrompt:
    def test_sections_present(self, tmp_path: Path) -> None:
        state = {
            "created_at": "2024-01-01T00:00:00Z",
            "tick_count": 7,
            "active_dispatches": [{"task_id": "t1"}],
            "escalations": [{"id": "e1", "tag": "tag", "diagnostic": "boom"}],
        }
        (tmp_path / "state.json").write_text("{}" if False else str(state).replace("'", '"'))
        # Write as real JSON
        import json
        (tmp_path / "state.json").write_text(json.dumps(state))
        prompt = generate_master_prompt(
            reason="do the thing",
            state_path=tmp_path / "state.json",
            status_path=tmp_path / "STATUS.csv",
        )
        assert "## 1. Base bootstrap" in prompt
        assert "## 2. Session state snapshot" in prompt
        assert "## 3. Wave plan delta" in prompt
        assert "## 4. Next-action queue" in prompt
        assert "## 5. Memory pointers" in prompt
        assert "do the thing" in prompt

    def test_fallback_when_no_bootstrap(self, tmp_path: Path) -> None:
        state = {"active_dispatches": []}
        import json
        (tmp_path / "state.json").write_text(json.dumps(state))
        with patch("harness.session.bootstrap._BOOTSTRAP_FALLBACKS", [tmp_path / "nonexistent.md"]):
            prompt = generate_master_prompt(
                state_path=tmp_path / "state.json",
                status_path=tmp_path / "STATUS.csv",
            )
        assert "(No bootstrap file found" in prompt


from unittest.mock import MagicMock
