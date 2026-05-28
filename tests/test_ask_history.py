"""W14-ASK-HISTORY 2026-05-28: tests for ask-history + ask-show
(Phase 2.3 of agentic-operator roadmap)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.ask_history import (
    list_asks,
    load_ask,
    render_ask_text,
    render_history_text,
)
from harness.cli import cli


def _make_ask_dir(
    reviews: Path, name: str, *,
    question: str = "Test?",
    mode: str = "routed",
    engines: list[str] | None = None,
    verdict: str | None = None,
    parent_id: str | None = None,
    total_cost: float = 0.01,
) -> Path:
    """Build a fake ask-* dir with question.md + summary.json (+
    per-engine .md files)."""
    d = reviews / name
    d.mkdir(parents=True, exist_ok=True)
    eng = engines or ["mimo-via-claude"]
    (d / "question.md").write_text(
        f"# Panel question\n\n{question}\n", encoding="utf-8",
    )
    summary: dict = {
        "question": question,
        "mode": mode,
        "timestamp": "2026-05-28T12:00:00Z",
        "results": [
            {"engine": e, "role": "" if mode != "audit" else
             ("producer" if i == 0 else "audit")}
            for i, e in enumerate(eng)
        ],
        "total_cost_usd": total_cost,
        "max_latency_s": 30.0,
    }
    if verdict:
        summary["verdict"] = {
            "verdict": verdict,
            "summary": "test",
            "corrections": "",
            "missed": "",
            "overall": "test",
            "raw": "...",
        }
    if parent_id:
        summary["parent_id"] = parent_id
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for e in eng:
        safe = e.replace("/", "_")
        (d / f"{safe}.md").write_text(
            f"# {e}\n\nresponse from {e}\n", encoding="utf-8",
        )
    return d


# ---------------------------------------------------------------------------
# list_asks + render_history_text
# ---------------------------------------------------------------------------


class TestListAsks:
    def test_empty_reviews_dir(self, tmp_path: Path) -> None:
        rows = list_asks(reviews_dir=tmp_path)
        assert rows == []

    def test_returns_newest_first(self, tmp_path: Path) -> None:
        # Timestamps embedded in dir names are the sort key
        for name in (
            "ask-20260526-001234-old",
            "ask-20260528-001234-newest",
            "ask-20260527-001234-middle",
        ):
            _make_ask_dir(tmp_path, name)
        rows = list_asks(reviews_dir=tmp_path)
        ids = [r["id"] for r in rows]
        assert ids[0].endswith("newest")
        assert ids[-1].endswith("old")

    def test_filter_by_mode(self, tmp_path: Path) -> None:
        _make_ask_dir(tmp_path, "ask-1-r", mode="routed")
        _make_ask_dir(tmp_path, "ask-2-a", mode="audit", verdict="PASS")
        _make_ask_dir(tmp_path, "ask-3-p", mode="panel")
        rows = list_asks(reviews_dir=tmp_path, mode_filter="audit")
        assert len(rows) == 1
        assert rows[0]["mode"] == "audit"

    def test_filter_by_verdict(self, tmp_path: Path) -> None:
        _make_ask_dir(tmp_path, "ask-pass", mode="audit", verdict="PASS")
        _make_ask_dir(tmp_path, "ask-fail", mode="audit", verdict="FAIL")
        _make_ask_dir(
            tmp_path, "ask-partial", mode="audit", verdict="PARTIAL",
        )
        rows = list_asks(reviews_dir=tmp_path, verdict_filter="FAIL")
        assert len(rows) == 1
        assert rows[0]["verdict"] == "FAIL"

    def test_verdict_filter_case_insensitive(self, tmp_path: Path) -> None:
        _make_ask_dir(tmp_path, "ask-pass", mode="audit", verdict="PASS")
        rows = list_asks(reviews_dir=tmp_path, verdict_filter="pass")
        assert len(rows) == 1

    def test_last_n_caps_results(self, tmp_path: Path) -> None:
        for i in range(10):
            _make_ask_dir(tmp_path, f"ask-2026052{i}-x")
        rows = list_asks(reviews_dir=tmp_path, last_n=3)
        assert len(rows) == 3

    def test_handles_missing_summary_json(self, tmp_path: Path) -> None:
        d = tmp_path / "ask-broken"
        d.mkdir()
        # No summary.json
        rows = list_asks(reviews_dir=tmp_path)
        assert len(rows) == 1
        assert rows[0]["id"] == "ask-broken"
        assert rows[0]["mode"] == "?"

    def test_handles_malformed_summary_json(self, tmp_path: Path) -> None:
        d = tmp_path / "ask-broken-json"
        d.mkdir()
        (d / "summary.json").write_text("not valid json", encoding="utf-8")
        rows = list_asks(reviews_dir=tmp_path)
        assert len(rows) == 1
        # Doesn't crash; fields default to safe values
        assert rows[0]["mode"] == "?"
        assert rows[0]["engines"] == []

    def test_extracts_parent_id_for_reruns(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-rerun-of-x", parent_id="ask-original-x",
        )
        rows = list_asks(reviews_dir=tmp_path)
        assert rows[0]["parent_id"] == "ask-original-x"


class TestRenderHistoryText:
    def test_empty(self) -> None:
        text = render_history_text([])
        assert "no asks" in text.lower()

    def test_includes_columns(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-20260528-x",
            question="Sample question",
            verdict="PARTIAL",
        )
        rows = list_asks(reviews_dir=tmp_path)
        text = render_history_text(rows)
        assert "ask-20260528-x" in text
        assert "Sample question" in text
        assert "PARTIAL" in text


# ---------------------------------------------------------------------------
# load_ask + render_ask_text
# ---------------------------------------------------------------------------


class TestLoadAsk:
    def test_unknown_id_returns_error(self, tmp_path: Path) -> None:
        data = load_ask("ask-does-not-exist", reviews_dir=tmp_path)
        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_reads_full_data(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-test",
            question="What is X?",
            mode="audit",
            engines=["mimo-via-claude", "deepseek-via-claude"],
            verdict="PASS",
        )
        data = load_ask("ask-test", reviews_dir=tmp_path)
        assert data["id"] == "ask-test"
        assert "What is X?" in data["question"]
        assert data["summary"]["mode"] == "audit"
        # Per-engine files captured
        assert "mimo-via-claude.md" in data["per_engine"]
        assert "deepseek-via-claude.md" in data["per_engine"]
        # Content of per-engine file present
        assert "response from mimo-via-claude" in (
            data["per_engine"]["mimo-via-claude.md"]
        )


class TestRenderAskText:
    def test_renders_question_mode_engines(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-render",
            question="Sample question",
            mode="routed",
            engines=["mimo-via-claude"],
        )
        data = load_ask("ask-render", reviews_dir=tmp_path)
        text = render_ask_text(data)
        assert "ask-render" in text
        assert "Sample question" in text
        assert "routed" in text
        assert "mimo-via-claude" in text

    def test_renders_audit_verdict(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-audit",
            mode="audit",
            engines=["mimo-via-claude", "deepseek-via-claude"],
            verdict="PARTIAL",
        )
        data = load_ask("ask-audit", reviews_dir=tmp_path)
        text = render_ask_text(data)
        assert "Verdict" in text
        assert "PARTIAL" in text

    def test_renders_parent_id_for_rerun(self, tmp_path: Path) -> None:
        _make_ask_dir(
            tmp_path, "ask-rerun",
            parent_id="ask-original-question",
        )
        data = load_ask("ask-rerun", reviews_dir=tmp_path)
        text = render_ask_text(data)
        assert "parent_id" in text
        assert "ask-original-question" in text
        # The "(this is a rerun)" hint must surface
        assert "rerun" in text.lower()


# ---------------------------------------------------------------------------
# CLI: harness ask-history
# ---------------------------------------------------------------------------


class TestAskHistoryCli:
    def test_runs_without_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ask-history", "--last", "5"])
        assert result.exit_code == 0

    def test_json_format(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["ask-history", "--last", "5", "--format", "json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)

    def test_help_mentions_rerun_pairing(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ask-history", "--help"])
        assert result.exit_code == 0
        assert "rerun" in result.output.lower()


class TestAskShowCli:
    def test_unknown_id_exits_nonzero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ask-show", "ask-does-not-exist"])
        assert result.exit_code == 1
        combined = result.output + (result.stderr or "")
        assert "not found" in combined.lower() or "error" in combined.lower()
