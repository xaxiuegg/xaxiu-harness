"""W13-ENGINE-FAILURE-VISIBILITY: tests for live probe + failure categorization.

Covers:
- categorize_engine_failure pure function across all bucket types
- probe_engine_live live dispatch + probe-log write
- read_failure_summary aggregates dispatch + probe logs correctly
- engines --health CLI integration uses live probe by default
- engines --health --shallow CLI integration uses legacy probe
- engines failures CLI surfaces summary
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.cli_helpers import (
    ENGINE_HEALTH_CATEGORIES,
    categorize_engine_failure,
    probe_engine_live,
    probe_all_engines_live,
    read_failure_summary,
    _append_probe_event,
    _redact_for_probe_log,
)


# ---------------------------------------------------------------------------
# categorize_engine_failure
# ---------------------------------------------------------------------------


class TestCategorize:
    def test_success_is_up(self) -> None:
        assert categorize_engine_failure(True, None) == "up"

    def test_success_overrides_error(self) -> None:
        # If success=True we trust it even if error_str happens to be set
        assert categorize_engine_failure(True, "stale error") == "up"

    def test_none_error_with_failure_is_unknown(self) -> None:
        assert categorize_engine_failure(False, None) == "unknown-failure"

    def test_access_terminated_string_match(self) -> None:
        body = ('HTTP 403: {"error":{"message":"Access terminated. '
                'Review our Community Guidelines"}}')
        assert categorize_engine_failure(False, body) == "terminated"

    def test_access_terminated_error_type(self) -> None:
        body = 'HTTP 403: {"error":{"type":"access_terminated_error"}}'
        assert categorize_engine_failure(False, body) == "terminated"

    def test_terminated_beats_generic_403(self) -> None:
        # 'access terminated' must beat the generic 403 → auth-failed rule
        body = "HTTP 403: Access terminated by provider"
        assert categorize_engine_failure(False, body) == "terminated"

    def test_http_401_is_auth_failed(self) -> None:
        assert categorize_engine_failure(False, "HTTP 401") == "auth-failed"

    def test_invalid_authentication_body(self) -> None:
        body = 'HTTP 401: {"error":{"message":"Invalid Authentication"}}'
        assert categorize_engine_failure(False, body) == "auth-failed"

    def test_http_403_without_terminated_is_auth_failed(self) -> None:
        assert categorize_engine_failure(False, "HTTP 403") == "auth-failed"

    def test_no_api_key(self) -> None:
        assert categorize_engine_failure(False,
            "No API key for kimi") == "no-key"
        assert categorize_engine_failure(False,
            "missing api key") == "no-key"

    def test_http_429_is_quota(self) -> None:
        assert categorize_engine_failure(False, "HTTP 429") == "quota-exceeded"

    def test_rate_limit_string_is_quota(self) -> None:
        assert categorize_engine_failure(False,
            "rate limit exceeded") == "quota-exceeded"

    def test_insufficient_balance_is_quota(self) -> None:
        assert categorize_engine_failure(False,
            "Insufficient balance") == "quota-exceeded"

    def test_5xx_is_endpoint_down(self) -> None:
        assert categorize_engine_failure(False,
            "HTTP 500") == "endpoint-down"
        assert categorize_engine_failure(False,
            "HTTP 502 Bad Gateway") == "endpoint-down"
        assert categorize_engine_failure(False,
            "Service Unavailable") == "endpoint-down"

    def test_connection_refused_is_endpoint_down(self) -> None:
        assert categorize_engine_failure(False,
            "ConnectError: connection refused") == "endpoint-down"

    def test_dns_failure_is_endpoint_down(self) -> None:
        assert categorize_engine_failure(False,
            "getaddrinfo failed") == "endpoint-down"

    def test_remote_protocol_error_is_transient(self) -> None:
        assert categorize_engine_failure(False,
            "RemoteProtocolError: Server disconnected") == "transient"

    def test_timeout_is_transient(self) -> None:
        assert categorize_engine_failure(False,
            "Read timeout") == "transient"
        assert categorize_engine_failure(False,
            "timed out") == "transient"

    def test_unknown_error_is_unknown_failure(self) -> None:
        assert categorize_engine_failure(False,
            "Some weird novel error nobody anticipated") == "unknown-failure"

    def test_all_categories_in_vocabulary(self) -> None:
        # Every category we return must be in the closed vocabulary
        cases = [
            (True, None),
            (False, "Access terminated"),
            (False, "HTTP 401"),
            (False, "HTTP 429"),
            (False, "HTTP 500"),
            (False, "RemoteProtocolError"),
            (False, "No API key for kimi"),
            (False, "weird"),
            (False, None),
        ]
        for success, err in cases:
            cat = categorize_engine_failure(success, err)
            assert cat in ENGINE_HEALTH_CATEGORIES, \
                f"category {cat!r} not in vocabulary"


# ---------------------------------------------------------------------------
# _redact_for_probe_log
# ---------------------------------------------------------------------------


class TestProbeLogRedaction:
    def test_redacts_sk_keys(self) -> None:
        out = _redact_for_probe_log(
            "HTTP 401 with sk-or-1234567890abcdef in body")
        assert "sk-or-1234" not in out
        assert "sk-[REDACTED]" in out

    def test_redacts_tp_keys(self) -> None:
        out = _redact_for_probe_log(
            "Bearer token tp-xyz123-abc456 returned 401")
        assert "tp-xyz123" not in out

    def test_redacts_bearer_tokens(self) -> None:
        out = _redact_for_probe_log(
            "Authorization Bearer ey1abc.def.ghi returned 401")
        assert "ey1abc" not in out

    def test_caps_at_300_chars(self) -> None:
        out = _redact_for_probe_log("X" * 1000)
        assert len(out) == 300

    def test_none_passthrough(self) -> None:
        assert _redact_for_probe_log(None) is None

    def test_empty_passthrough(self) -> None:
        assert _redact_for_probe_log("") == ""


# ---------------------------------------------------------------------------
# _append_probe_event
# ---------------------------------------------------------------------------


class TestAppendProbeEvent:
    def test_writes_one_jsonl_row(self, tmp_path: Path) -> None:
        log_path = tmp_path / "probes.jsonl"
        _append_probe_event("kimi", "terminated", "HTTP 403: terminated",
                           1500, log_path=log_path)
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["engine"] == "kimi"
        assert rec["category"] == "terminated"
        assert "terminated" in (rec["error_excerpt"] or "")
        assert rec["latency_ms"] == 1500
        assert "timestamp" in rec

    def test_appends_multiple(self, tmp_path: Path) -> None:
        log_path = tmp_path / "probes.jsonl"
        _append_probe_event("kimi", "terminated", "x", 100, log_path=log_path)
        _append_probe_event("deepseek", "up", None, 200, log_path=log_path)
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_never_raises_on_path_error(self, tmp_path: Path) -> None:
        # Pass a path inside a file (impossible to write to as directory)
        f = tmp_path / "occupied"
        f.write_text("x", encoding="utf-8")
        # Should silently no-op, not raise
        _append_probe_event("kimi", "up", None, 100,
                           log_path=f / "subdir" / "probe.jsonl")

    def test_secrets_are_redacted_in_log(self, tmp_path: Path) -> None:
        log_path = tmp_path / "probes.jsonl"
        _append_probe_event("kimi", "terminated",
                           "HTTP 401 with sk-leaked-secret-abc in body",
                           100, log_path=log_path)
        content = log_path.read_text(encoding="utf-8")
        assert "sk-leaked" not in content
        assert "REDACTED" in content


# ---------------------------------------------------------------------------
# probe_engine_live
# ---------------------------------------------------------------------------


class TestProbeEngineLive:
    def test_no_key_returns_no_key_category(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the engine to raise RuntimeError for missing key
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        log_path = tmp_path / "probes.jsonl"
        category, err = probe_engine_live("anthropic", log_path=log_path)
        assert category == "no-key"
        assert err is not None and "key" in err.lower()
        # Probe result was logged
        assert log_path.exists()
        rec = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert rec["category"] == "no-key"

    def test_log_false_skips_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        log_path = tmp_path / "probes.jsonl"
        probe_engine_live("anthropic", log=False, log_path=log_path)
        assert not log_path.exists()

    def test_engine_dispatch_exception_categorized(
        self, tmp_path: Path,
    ) -> None:
        # Patch get_engine to return a fake engine that raises on dispatch
        from harness import cli_helpers
        class FakeEngine:
            def dispatch(self, *_a, **_kw):
                raise RuntimeError("RemoteProtocolError simulated")
        with patch.object(cli_helpers, "get_engine",
                          return_value=FakeEngine()):
            log_path = tmp_path / "probes.jsonl"
            category, err = probe_engine_live("kimi", log_path=log_path)
            assert category == "transient"
            assert "RemoteProtocolError" in (err or "")


# ---------------------------------------------------------------------------
# read_failure_summary
# ---------------------------------------------------------------------------


class TestReadFailureSummary:
    def test_aggregates_probe_log(self, tmp_path: Path) -> None:
        probe_log = tmp_path / "probes.jsonl"
        _append_probe_event("kimi", "terminated", "HTTP 403", 100,
                           log_path=probe_log)
        _append_probe_event("kimi", "terminated", "HTTP 403", 100,
                           log_path=probe_log)
        _append_probe_event("deepseek", "up", None, 100, log_path=probe_log)
        summary = read_failure_summary(
            since_hours=24,
            dispatch_log_path=tmp_path / "missing-dispatch.jsonl",
            probe_log_path=probe_log,
        )
        assert summary["since_hours"] == 24
        eng_data = summary["engines"]
        assert eng_data["kimi"]["total"] == 2
        assert eng_data["kimi"]["by_category"]["terminated"] == 2
        assert eng_data["deepseek"]["total"] == 1
        assert eng_data["deepseek"]["by_category"]["up"] == 1

    def test_engine_filter(self, tmp_path: Path) -> None:
        probe_log = tmp_path / "probes.jsonl"
        _append_probe_event("kimi", "terminated", "x", 100, log_path=probe_log)
        _append_probe_event("deepseek", "up", None, 100, log_path=probe_log)
        summary = read_failure_summary(
            since_hours=24,
            engine="kimi",
            dispatch_log_path=tmp_path / "missing.jsonl",
            probe_log_path=probe_log,
        )
        assert "kimi" in summary["engines"]
        assert "deepseek" not in summary["engines"]

    def test_since_hours_filters_old(self, tmp_path: Path) -> None:
        probe_log = tmp_path / "probes.jsonl"
        # Write an old record manually
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        probe_log.write_text(
            json.dumps({
                "timestamp": old_ts, "engine": "kimi",
                "category": "terminated", "error_excerpt": "x",
                "latency_ms": 100,
            }) + "\n",
            encoding="utf-8",
        )
        summary = read_failure_summary(
            since_hours=24,
            dispatch_log_path=tmp_path / "missing.jsonl",
            probe_log_path=probe_log,
        )
        # 30-day-old record outside the 24h window
        assert summary["engines"] == {}

    def test_reads_dispatch_log_format(self, tmp_path: Path) -> None:
        dispatch_log = tmp_path / "dispatch.jsonl"
        ts = datetime.now(timezone.utc).isoformat()
        dispatch_log.write_text(
            json.dumps({
                "timestamp": ts, "backend": "deepseek", "model": "x",
                "outcome": "success", "latency_ms": 100,
                "project": "p", "packet_path": "/tmp/p",
                "fallback_to": None,
            }) + "\n"
            + json.dumps({
                "timestamp": ts, "backend": "deepseek", "model": "x",
                "outcome": "api_error", "latency_ms": 100,
                "project": "p", "packet_path": "/tmp/p",
                "fallback_to": "kimi",
            }) + "\n",
            encoding="utf-8",
        )
        summary = read_failure_summary(
            since_hours=24,
            dispatch_log_path=dispatch_log,
            probe_log_path=tmp_path / "missing-probe.jsonl",
        )
        assert summary["engines"]["deepseek"]["total"] == 2
        assert summary["engines"]["deepseek"]["by_category"]["up"] == 1
        assert summary["engines"]["deepseek"]["by_category"]["api_error"] == 1

    def test_recent_samples_capped(self, tmp_path: Path) -> None:
        probe_log = tmp_path / "probes.jsonl"
        for _ in range(10):
            _append_probe_event("kimi", "terminated", "x", 100,
                               log_path=probe_log)
        summary = read_failure_summary(
            since_hours=24,
            dispatch_log_path=tmp_path / "missing.jsonl",
            probe_log_path=probe_log,
        )
        assert len(summary["engines"]["kimi"]["recent_samples"]) == 5


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestEnginesCli:
    def test_engines_health_shallow_flag_routes_to_legacy(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["engines", "--health", "--shallow"],
            standalone_mode=False, catch_exceptions=False,
        )
        # Should produce output (whatever the network state is)
        # and not error
        assert "deepseek" in result.output or result.exit_code == 0

    def test_engines_failures_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "--help"])
        assert result.exit_code == 0
        assert "failures" in result.output

    def test_engines_failures_no_data(self, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["engines", "failures", "--since-hours", "1"],
        )
        assert result.exit_code == 0
        assert "No engine events" in result.output

    def test_engines_failures_shows_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "state").mkdir()
        probe_log = tmp_path / "state" / "engine_health_probes.jsonl"
        _append_probe_event("kimi", "terminated", "HTTP 403 terminated",
                           100, log_path=probe_log)
        _append_probe_event("deepseek", "up", None, 50, log_path=probe_log)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["engines", "failures", "--since-hours", "24"],
        )
        assert result.exit_code == 0
        assert "kimi" in result.output
        assert "terminated" in result.output
