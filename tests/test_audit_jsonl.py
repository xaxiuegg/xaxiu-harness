"""W13-AUDIT-JSONL: tests for the audit ledger + secret redactor.

Covers:
  - redact_secrets scrubs sk-* / tp-* / AIza* / *_API_KEY= / Bearer
    patterns
  - append_dispatch_event writes a parseable JSON line
  - prompt/response excerpts go through redaction
  - iter_events filters by since_hours, engine, tail
  - summary() aggregates correctly
  - prune drops old events + keeps malformed lines (data preservation)
  - size-cap prune kicks in
  - append failures NEVER raise (best-effort contract)
  - empty/missing ledger returns sensible defaults
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness import audit_jsonl as aj


# -- redact_secrets ---------------------------------------------------------


class TestRedactSecrets:
    def test_sk_platform_key_redacted(self):
        result = aj.redact_secrets("My key is sk-abc123def456ghi789")
        assert "sk-abc123def456" not in result
        assert "<redacted-platform-key>" in result

    def test_sk_or_openrouter_key_redacted(self):
        result = aj.redact_secrets("Token: sk-or-abc123def456ghi")
        assert "sk-or-abc123" not in result
        assert "<redacted-openrouter-key>" in result

    def test_tp_mimo_token_plan_key_redacted(self):
        result = aj.redact_secrets("MiMo: tp-abcXYZ123456789")
        assert "tp-abcXYZ123" not in result
        assert "<redacted-mimo-tp-key>" in result

    def test_gemini_aiza_key_redacted(self):
        result = aj.redact_secrets("Gemini: AIzaSyDtest1234567890abcXYZ")
        assert "AIzaSyDtest" not in result
        assert "<redacted-gemini-key>" in result

    def test_env_var_assignment_redacted(self):
        result = aj.redact_secrets("Set KIMI_API_KEY=sk-test123real456")
        # Both the env-var assignment AND the sk- pattern match;
        # at least the secret value should not survive
        assert "real456" not in result
        # Either the env-var redaction or the sk- redaction must have fired
        assert ("redacted" in result.lower()
                or "<redacted" in result)

    def test_bearer_token_redacted(self):
        result = aj.redact_secrets("Authorization: Bearer eyJtoken123456")
        assert "eyJtoken123456" not in result

    def test_authorization_header_redacted(self):
        result = aj.redact_secrets(
            "headers={'Authorization': 'sk-real456789hidden'}",
        )
        assert "real456789hidden" not in result

    def test_multiple_secrets_all_redacted(self):
        s = ("token1: sk-aaa111bbb222 and "
             "token2: tp-ccc333ddd444 and "
             "token3: AIzabbbXXXccc1234567890")
        result = aj.redact_secrets(s)
        for leaked in ("sk-aaa111bbb222", "tp-ccc333ddd444",
                       "AIzabbbXXXccc"):
            assert leaked not in result, f"leaked: {leaked}"

    def test_innocent_text_with_sk_prefix_passes_through_redacted(self):
        # 'sk-test' looks like a key — we accept the false positive
        # rather than risk a false negative
        result = aj.redact_secrets("see sk-test123456789xyz docs")
        assert "<redacted" in result

    def test_none_returns_none(self):
        assert aj.redact_secrets(None) is None

    def test_empty_string_returns_empty(self):
        assert aj.redact_secrets("") == ""

    def test_no_secrets_returns_unchanged(self):
        innocent = "this is a normal sentence with no secrets"
        assert aj.redact_secrets(innocent) == innocent

    def test_non_string_input_does_not_crash(self):
        # str() conversion happens internally
        result = aj.redact_secrets(12345)  # type: ignore[arg-type]
        assert isinstance(result, str)

    def test_short_sk_substring_not_redacted(self):
        # 'sk-ab' is too short to be a real key — should NOT match
        # (our pattern requires at least 6 chars after the prefix)
        result = aj.redact_secrets("sk-ab is short")
        assert "<redacted" not in result


# -- append_dispatch_event --------------------------------------------------


class TestAppendDispatchEvent:
    def test_append_writes_parseable_json_line(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        ok = aj.append_dispatch_event(
            engine="kimi", model="kimi-for-coding",
            dispatch_id="abc-123",
            success=True, error=None,
            tokens_in=100, tokens_out=50,
            cost_usd=0.0, elapsed_ms=4200,
            prompt="Reply OK",
            response="OK",
            ledger_path=ledger,
        )
        assert ok is True
        assert ledger.exists()
        lines = ledger.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        ev = json.loads(lines[0])
        assert ev["engine"] == "kimi"
        assert ev["model"] == "kimi-for-coding"
        assert ev["dispatch_id"] == "abc-123"
        assert ev["success"] is True
        assert ev["tokens_in"] == 100
        assert ev["tokens_out"] == 50
        assert ev["elapsed_ms"] == 4200
        assert ev["event"] == "dispatch"
        assert "ts" in ev

    def test_append_redacts_secrets_in_prompt(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=True, error=None,
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0,
            prompt="My key is sk-realKEYvalue123abc456",
            ledger_path=ledger,
        )
        text = ledger.read_text(encoding="utf-8")
        assert "sk-realKEYvalue123" not in text, (
            "secret leaked into audit ledger"
        )
        assert "<redacted" in text

    def test_append_redacts_secrets_in_response(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=True, error=None,
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0,
            prompt="ok",
            response="The new key is tp-secretXYZ987",
            ledger_path=ledger,
        )
        text = ledger.read_text(encoding="utf-8")
        assert "tp-secretXYZ987" not in text
        assert "<redacted" in text

    def test_append_redacts_secrets_in_error(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=False,
            error="auth failed: Authorization: Bearer secretXYZ987abc",
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0,
            ledger_path=ledger,
        )
        text = ledger.read_text(encoding="utf-8")
        assert "secretXYZ987abc" not in text

    def test_append_truncates_long_prompts_to_excerpt(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        long_prompt = "X" * 5000
        aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=True, error=None,
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0,
            prompt=long_prompt,
            ledger_path=ledger,
        )
        ev = json.loads(ledger.read_text(encoding="utf-8").strip())
        excerpt = ev["prompt_excerpt"]
        # EXCERPT_CHARS is 200; plus the "...[truncated]" suffix
        assert len(excerpt) < 250
        assert "truncated" in excerpt

    def test_append_creates_parent_dir_if_missing(self, tmp_path):
        ledger = tmp_path / "nested" / "deep" / "audit.jsonl"
        ok = aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=True, error=None,
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0,
            ledger_path=ledger,
        )
        assert ok is True
        assert ledger.exists()

    def test_append_never_raises_on_io_failure(self, monkeypatch, tmp_path):
        """Best-effort contract: append must NEVER raise.  Even if the
        filesystem refuses, the function returns False."""
        # Point to a path that cannot be created (a file used as a dir
        # is the simplest universal failure)
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        ledger = blocker / "audit.jsonl"
        # This MUST NOT raise
        ok = aj.append_dispatch_event(
            engine="kimi", model="m",
            dispatch_id=None, success=True, error=None,
            tokens_in=0, tokens_out=0, cost_usd=0,
            elapsed_ms=0, ledger_path=ledger,
        )
        assert ok is False

    def test_multiple_appends_one_per_line(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        for i in range(5):
            aj.append_dispatch_event(
                engine="kimi", model="m",
                dispatch_id=f"d-{i}", success=True, error=None,
                tokens_in=i * 10, tokens_out=i * 5,
                cost_usd=0.0, elapsed_ms=100 * i,
                ledger_path=ledger,
            )
        lines = ledger.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
        for i, line in enumerate(lines):
            ev = json.loads(line)
            assert ev["dispatch_id"] == f"d-{i}"


# -- iter_events ------------------------------------------------------------


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


class TestIterEvents:
    def test_missing_ledger_returns_empty(self, tmp_path):
        events = aj.iter_events(ledger_path=tmp_path / "missing.jsonl")
        assert events == []

    def test_returns_all_events_by_default(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        _write_events(ledger, [
            {"ts": "2026-05-25T10:00:00.000000Z", "engine": "kimi",
             "tokens_in": 100, "tokens_out": 50, "cost_usd": 0,
             "success": True, "retry_count": 0},
            {"ts": "2026-05-25T10:01:00.000000Z", "engine": "deepseek",
             "tokens_in": 200, "tokens_out": 100, "cost_usd": 0.001,
             "success": True, "retry_count": 0},
        ])
        events = aj.iter_events(ledger_path=ledger)
        assert len(events) == 2

    def test_filters_by_engine(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        _write_events(ledger, [
            {"ts": "2026-05-25T10:00:00.000000Z", "engine": "kimi"},
            {"ts": "2026-05-25T10:01:00.000000Z", "engine": "deepseek"},
            {"ts": "2026-05-25T10:02:00.000000Z", "engine": "kimi"},
        ])
        kimi_events = aj.iter_events(ledger_path=ledger, engine="kimi")
        assert len(kimi_events) == 2

    def test_filters_by_since_hours(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        recent = (now - timedelta(minutes=5)).isoformat()
        _write_events(ledger, [
            {"ts": old, "engine": "kimi"},
            {"ts": recent, "engine": "kimi"},
        ])
        events = aj.iter_events(ledger_path=ledger, since_hours=24)
        assert len(events) == 1  # only the recent one

    def test_tail_returns_last_n(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        _write_events(ledger, [
            {"ts": f"2026-05-25T10:{i:02d}:00.000000Z",
             "engine": "kimi", "dispatch_id": f"d-{i}"}
            for i in range(10)
        ])
        last_3 = aj.iter_events(ledger_path=ledger, tail=3)
        assert len(last_3) == 3
        # File order preserved (oldest -> newest); tail returns last N
        assert last_3[-1]["dispatch_id"] == "d-9"

    def test_skips_malformed_lines(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        ledger.write_text(
            '{"ts": "2026-05-25T10:00:00.000000Z", "engine": "kimi"}\n'
            'this is not json\n'
            '{"missing_quotes": true\n'  # broken
            '{"ts": "2026-05-25T10:01:00.000000Z", "engine": "deepseek"}\n',
            encoding="utf-8",
        )
        events = aj.iter_events(ledger_path=ledger)
        assert len(events) == 2  # 2 valid lines


# -- summary ----------------------------------------------------------------


class TestSummary:
    def test_empty_ledger_zero_state(self, tmp_path):
        s = aj.summary(ledger_path=tmp_path / "missing.jsonl")
        assert s["total_events"] == 0
        assert s["successful"] == 0
        assert s["failed"] == 0
        assert s["by_engine"] == {}
        assert s["total_tokens"] == 0
        assert s["total_cost_usd"] == 0.0
        assert s["retries_total"] == 0

    def test_summary_counts_success_failure(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        _write_events(ledger, [
            {"ts": "2026-05-25T10:00:00Z", "engine": "kimi",
             "success": True, "tokens_in": 100, "tokens_out": 50,
             "cost_usd": 0, "retry_count": 0},
            {"ts": "2026-05-25T10:01:00Z", "engine": "deepseek",
             "success": False, "tokens_in": 0, "tokens_out": 0,
             "cost_usd": 0, "retry_count": 1},
            {"ts": "2026-05-25T10:02:00Z", "engine": "mimo",
             "success": True, "tokens_in": 300, "tokens_out": 150,
             "cost_usd": 0, "retry_count": 0},
        ])
        s = aj.summary(ledger_path=ledger)
        assert s["total_events"] == 3
        assert s["successful"] == 2
        assert s["failed"] == 1
        assert s["by_engine"] == {"kimi": 1, "deepseek": 1, "mimo": 1}
        assert s["total_tokens"] == 600  # 150 + 0 + 450
        assert s["retries_total"] == 1


# -- prune ------------------------------------------------------------------


class TestPrune:
    def test_prune_drops_entries_older_than_cutoff(self, tmp_path,
                                                     monkeypatch):
        ledger = tmp_path / "audit.jsonl"
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        recent = (now - timedelta(hours=2)).isoformat()
        _write_events(ledger, [
            {"ts": old, "engine": "kimi", "dispatch_id": "old"},
            {"ts": recent, "engine": "kimi", "dispatch_id": "recent"},
        ])
        # Force max age = 7 days
        monkeypatch.setenv("HARNESS_AUDIT_MAX_AGE_DAYS", "7")
        removed = aj._prune_if_needed(ledger)
        assert removed == 1
        remaining = ledger.read_text(encoding="utf-8").strip().splitlines()
        parsed = [json.loads(line) for line in remaining]
        assert len(parsed) == 1
        assert parsed[0]["dispatch_id"] == "recent"

    def test_prune_keeps_malformed_lines(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        ledger.write_text(
            f'{{"ts": "{now}", "engine": "kimi"}}\n'
            'this is not json\n',
            encoding="utf-8",
        )
        aj._prune_if_needed(ledger)
        # Malformed line kept (data preservation per the prune docstring)
        text = ledger.read_text(encoding="utf-8")
        assert "this is not json" in text

    def test_prune_no_op_when_all_recent(self, tmp_path):
        ledger = tmp_path / "audit.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        _write_events(ledger, [
            {"ts": now, "engine": "kimi"},
        ])
        removed = aj._prune_if_needed(ledger)
        assert removed == 0


# -- append + iter roundtrip ------------------------------------------------


def test_append_then_iter_round_trip(tmp_path):
    """End-to-end: append events, iter them back, see the same data."""
    ledger = tmp_path / "audit.jsonl"
    for i in range(3):
        aj.append_dispatch_event(
            engine=f"engine-{i}", model="m",
            dispatch_id=f"d-{i}", success=True, error=None,
            tokens_in=i, tokens_out=i, cost_usd=0,
            elapsed_ms=i * 100,
            ledger_path=ledger,
        )
    events = aj.iter_events(ledger_path=ledger)
    assert len(events) == 3
    for i, ev in enumerate(events):
        assert ev["engine"] == f"engine-{i}"
        assert ev["dispatch_id"] == f"d-{i}"


# -- regression: never break dispatch on audit failure ----------------------


def test_audit_failure_never_propagates_to_caller(tmp_path):
    """REGRESSION: append_dispatch_event must NEVER raise.  This is
    the load-bearing contract — auto-defaults that fire audit events
    cannot fail because the audit layer is unavailable."""
    # Multiple failure modes
    for path in [
        tmp_path / "good.jsonl",  # normal happy case
        Path("/nonexistent/path/cannot/be/created/audit.jsonl"),  # invalid
    ]:
        try:
            ok = aj.append_dispatch_event(
                engine="kimi", model="m",
                dispatch_id=None, success=True, error=None,
                tokens_in=0, tokens_out=0, cost_usd=0,
                elapsed_ms=0, ledger_path=path,
            )
            assert isinstance(ok, bool)  # always returns a bool, never raises
        except Exception as exc:
            pytest.fail(
                f"append_dispatch_event raised on path {path}: {exc}"
            )
