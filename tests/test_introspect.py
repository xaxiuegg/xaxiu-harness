"""W14-INTROSPECT 2026-05-28: tests for the single-call capability +
state snapshot (Phase 2.1 of agentic-operator roadmap)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.introspect import (
    build_snapshot,
    render_text,
    _check_agent_instructions,
    _check_proxy_state,
    _doctor_summary,
    _harness_version,
    _recent_asks,
    _repo_root,
    _summarize_engines,
    _summarize_wrappers,
)


class TestVersion:
    def test_returns_string(self) -> None:
        v = _harness_version()
        assert isinstance(v, str)
        assert v  # not empty


class TestRepoRoot:
    def test_points_to_project_root(self) -> None:
        root = _repo_root()
        # The project root must contain CHANGELOG.md and pyproject.toml
        assert (root / "CHANGELOG.md").exists()
        assert (root / "pyproject.toml").exists()


class TestCheckProxyState:
    def test_returns_dict_with_expected_keys(self) -> None:
        state = _check_proxy_state()
        assert isinstance(state, dict)
        # Always present
        for key in ("running", "pid", "endpoint", "upstream", "pool_size"):
            assert key in state

    def test_running_false_when_pid_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        # No .harness/proxy.pid in tmp_path
        state = _check_proxy_state()
        assert state["running"] is False
        assert state["pid"] is None

    def test_running_true_when_pid_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".harness").mkdir()
        (tmp_path / ".harness" / "proxy.pid").write_text("12345")
        state = _check_proxy_state()
        assert state["running"] is True
        assert state["pid"] == 12345


class TestSummarizeEngines:
    def test_returns_one_row_per_metadata_engine(self) -> None:
        rows = _summarize_engines()
        from harness.engines.metadata import list_engine_metadata
        assert len(rows) == len(list_engine_metadata())

    def test_required_fields_present(self) -> None:
        rows = _summarize_engines()
        for r in rows:
            for key in (
                "engine", "vendor", "key_env", "key_present",
                "key_count", "protocols", "ua_gated",
                "default_model", "latency_class", "recommended_for",
            ):
                assert key in r, f"missing {key} in row {r['engine']}"

    def test_mimo_has_dual_protocols_in_snapshot(self) -> None:
        """The transcript-canonical-hiccup metadata propagates into the
        introspect snapshot too."""
        rows = {r["engine"]: r for r in _summarize_engines()}
        mimo = rows["mimo-via-claude"]
        assert set(mimo["protocols"]) >= {"openai", "anthropic"}
        assert mimo["ua_gated"] is True


class TestCheckAgentInstructions:
    def test_missing_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Point HOME at a tmp dir with no CLAUDE.md
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result = _check_agent_instructions()
        assert result["installed"] is False
        assert result["current"] is False
        assert "snippet not installed" in result["hint"].lower() or \
               "not installed" in result["hint"].lower() or \
               "install-agent-instructions" in result["hint"]

    def test_installed_no_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True)
        claude_md.write_text("# my personal notes\n", encoding="utf-8")
        result = _check_agent_instructions()
        # File exists but no harness markers
        assert result["installed"] is False
        assert "marker" in result["hint"].lower() or \
               "install-agent-instructions" in result["hint"]

    def test_installed_with_current_snippet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # Install the CURRENT snippet (matches the template)
        from harness.cli import _agent_instructions_snippet
        from harness import __version__ as _v
        fresh = _agent_instructions_snippet(
            "claude-md", _repo_root(), tmp_path,
        )
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True)
        claude_md.write_text(
            f"\n<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START v{_v} -->\n"
            "<!-- Auto-installed by `harness install-agent-instructions`. -->\n\n"
            + fresh.strip() + "\n"
            "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->\n",
            encoding="utf-8",
        )
        result = _check_agent_instructions()
        assert result["installed"] is True
        assert result["current"] is True
        # Both hashes should match
        assert result["installed_hash"] == result["current_hash"]
        # Versioned install: introspect surfaces the version
        assert result["installed_version"] == _v
        assert result["current_version"] == _v

    def test_installed_unversioned_still_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-v0.5.7 installs had no version stamp in the START
        marker.  introspect must still detect + treat them as stale
        (forcing the operator to --force refresh)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True)
        claude_md.write_text(
            "\n<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->\n"
            "<!-- Auto-installed. -->\n\n"
            "## xaxiu-harness is available\n\n"
            "(stale pre-v0.5.7 content)\n"
            "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->\n",
            encoding="utf-8",
        )
        result = _check_agent_instructions()
        # Detected as installed (prefix matched the un-versioned marker)
        assert result["installed"] is True
        # No version recoverable from the marker
        assert result["installed_version"] is None
        # Body doesn't match current → STALE
        assert result["current"] is False

    def test_installed_but_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # Install a STALE snippet — older version with different content
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True)
        claude_md.write_text(
            "\n<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START v0.5.4 -->\n"
            "<!-- Auto-installed by `harness install-agent-instructions`. -->\n\n"
            "## xaxiu-harness is available\n\n"
            "old template — fires 3 engines (Kimi / MiMo / DeepSeek) "
            "in parallel.\n"
            "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->\n",
            encoding="utf-8",
        )
        result = _check_agent_instructions()
        assert result["installed"] is True
        assert result["current"] is False
        # Hint must direct user to --force refresh
        assert "--force" in result["hint"] or "force" in result["hint"]
        # Stale version surfaces in hint
        assert result["installed_version"] == "0.5.4"
        # Both versions appear in the hint message
        assert "0.5.4" in result["hint"]


class TestSummarizeWrappers:
    def test_returns_dict_with_expected_keys(self) -> None:
        result = _summarize_wrappers()
        for key in ("wrappers", "dir", "on_path"):
            assert key in result
        assert isinstance(result["wrappers"], list)


class TestDoctorSummary:
    def test_returns_dict_with_overall(self) -> None:
        d = _doctor_summary(probe=False)
        # Either {"overall": ..., "counts": ...} or {"error": ...} shape
        assert "overall" in d


class TestRecentAsks:
    def test_empty_dir_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Redirect _repo_root by patching
        with patch("harness.introspect._repo_root", return_value=tmp_path):
            assert _recent_asks() == []

    def test_reads_summary_json(
        self, tmp_path: Path,
    ) -> None:
        reviews = tmp_path / "coord" / "reviews"
        reviews.mkdir(parents=True)
        ask_dir = reviews / "ask-20260528-test-q"
        ask_dir.mkdir()
        (ask_dir / "summary.json").write_text(json.dumps({
            "question": "Test?",
            "mode": "routed",
            "results": [{"engine": "mimo-via-claude"}],
            "total_cost_usd": 0.0125,
        }), encoding="utf-8")
        with patch("harness.introspect._repo_root", return_value=tmp_path):
            rows = _recent_asks(limit=5)
        assert len(rows) == 1
        assert rows[0]["mode"] == "routed"
        assert rows[0]["engines"] == ["mimo-via-claude"]
        assert rows[0]["total_cost_usd"] == 0.0125

    def test_extracts_verdict_for_audit(
        self, tmp_path: Path,
    ) -> None:
        reviews = tmp_path / "coord" / "reviews"
        reviews.mkdir(parents=True)
        ask_dir = reviews / "ask-20260528-audit-test"
        ask_dir.mkdir()
        (ask_dir / "summary.json").write_text(json.dumps({
            "question": "fact check",
            "mode": "audit",
            "results": [],
            "total_cost_usd": 0.05,
            "verdict": {"verdict": "PARTIAL", "summary": "..."},
        }), encoding="utf-8")
        with patch("harness.introspect._repo_root", return_value=tmp_path):
            rows = _recent_asks(limit=5)
        assert rows[0]["verdict"] == "PARTIAL"

    def test_handles_missing_summary_json(
        self, tmp_path: Path,
    ) -> None:
        reviews = tmp_path / "coord" / "reviews"
        reviews.mkdir(parents=True)
        ask_dir = reviews / "ask-20260528-broken"
        ask_dir.mkdir()  # no summary.json inside
        with patch("harness.introspect._repo_root", return_value=tmp_path):
            rows = _recent_asks(limit=5)
        assert len(rows) == 1
        assert rows[0]["mode"] == "?"  # unknown mode for missing summary

    def test_returns_newest_first(
        self, tmp_path: Path,
    ) -> None:
        reviews = tmp_path / "coord" / "reviews"
        reviews.mkdir(parents=True)
        for ts in ["20260526-001234", "20260527-001234", "20260528-001234"]:
            d = reviews / f"ask-{ts}-q"
            d.mkdir()
            (d / "summary.json").write_text(json.dumps({
                "mode": "routed", "results": [],
            }), encoding="utf-8")
        with patch("harness.introspect._repo_root", return_value=tmp_path):
            rows = _recent_asks(limit=10)
        # ID sorted descending by timestamp
        assert rows[0]["id"].startswith("ask-20260528")
        assert rows[-1]["id"].startswith("ask-20260526")


class TestBuildSnapshot:
    def test_top_level_keys_present(self) -> None:
        snap = build_snapshot(probe=False)
        for key in (
            "version", "harness_path", "timestamp",
            "verbs", "engines", "agent_instructions",
            "wrappers", "doctor", "recent_asks",
        ):
            assert key in snap, f"missing top-level key: {key}"

    def test_verbs_section_lists_ask_modes(self) -> None:
        snap = build_snapshot(probe=False)
        ask = snap["verbs"]["ask"]
        assert set(ask["modes"]) == {"routed", "audit", "panel"}
        assert ask["default_mode"] == "routed"

    def test_verbs_section_lists_proxy_upstreams(self) -> None:
        snap = build_snapshot(probe=False)
        upstreams = set(snap["verbs"]["proxy"]["upstream_options"])
        # All 4 W14-PROXY-UPSTREAMS entries surface here (qwen-http retired 2026-06-01)
        assert {
            "kimi-http", "deepseek-http",
            "mimo-via-claude-code", "kimi-via-claude-code",
        }.issubset(upstreams)

    def test_engines_section_has_all_known(self) -> None:
        snap = build_snapshot(probe=False)
        names = {e["engine"] for e in snap["engines"]}
        # At minimum, the 4 routable + 2 reference engines
        assert {
            "mimo-via-claude", "deepseek-via-claude",
            "kimi-via-claude", "qwen-via-claude",
            "anthropic", "gemini",
        }.issubset(names)


class TestRenderText:
    def test_does_not_crash_on_full_snapshot(self) -> None:
        snap = build_snapshot(probe=False)
        text = render_text(snap)
        assert isinstance(text, str)
        # Headers present
        assert "harness introspect" in text
        assert "Available verbs" in text
        assert "Engines" in text
        assert "Agent-instructions snippet" in text
        assert "Doctor summary" in text

    def test_proxy_upstream_options_visible_in_text(self) -> None:
        snap = build_snapshot(probe=False)
        text = render_text(snap)
        # All 5 upstream names visible (closing the discoverability gap)
        assert "kimi-http" in text
        assert "mimo-via-claude-code" in text
        assert "deepseek-http" in text


class TestIntrospectCli:
    def test_text_format_default(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["introspect"])
        assert result.exit_code == 0
        assert "harness introspect" in result.output
        # Key sections visible
        assert "Available verbs" in result.output
        assert "Engines" in result.output

    def test_json_format(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["introspect", "--format", "json"])
        assert result.exit_code == 0
        # Output must be parseable JSON
        parsed = json.loads(result.output)
        assert "version" in parsed
        assert "verbs" in parsed
        assert "engines" in parsed
        # All 5 upstreams reachable from JSON
        upstreams = set(parsed["verbs"]["proxy"]["upstream_options"])
        assert "mimo-via-claude-code" in upstreams

    def test_help_describes_purpose(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["introspect", "--help"])
        assert result.exit_code == 0
        # Help mentions the purpose
        assert "snapshot" in result.output.lower() or \
               "capability" in result.output.lower()
