"""W11-AGENT-TELEMETRY: tests for harness.budget_status() agent telemetry.

Spec from W11 plan + panel C4:
    Returns a dict: {session_tokens_total, session_cost_total,
                     offload_ratio, remaining_budget_usd,
                     dispatches_fired, engines_used: {kimi: N, ...},
                     avg_cost_per_token, cost_max_per_session_usd}
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness


@pytest.fixture
def empty_ledger(tmp_path):
    """Empty (zero-entry) ledger; budget_status returns all zeros."""
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def multi_engine_ledger(tmp_path):
    """Ledger with 5 dispatches across kimi, deepseek, mimo (mix
    of subscription + paid)."""
    entries = [
        # Kimi (subscription; cost=0)
        {"timestamp": "2026-05-25T10:00:00+00:00", "task_id": "t1",
         "engine": "kimi", "model": "kimi-k2.6",
         "input_tokens": 100, "output_tokens": 200,
         "latency_ms": 1500, "cost_usd": 0.0},
        {"timestamp": "2026-05-25T10:01:00+00:00", "task_id": "t2",
         "engine": "kimi", "model": "kimi-k2.6",
         "input_tokens": 200, "output_tokens": 300,
         "latency_ms": 1800, "cost_usd": 0.0},
        # DeepSeek (paid)
        {"timestamp": "2026-05-25T10:02:00+00:00", "task_id": "t3",
         "engine": "deepseek", "model": "deepseek-v4-flash",
         "input_tokens": 500, "output_tokens": 1000,
         "latency_ms": 800, "cost_usd": 0.0006},
        {"timestamp": "2026-05-25T10:03:00+00:00", "task_id": "t4",
         "engine": "deepseek", "model": "deepseek-v4-flash",
         "input_tokens": 300, "output_tokens": 800,
         "latency_ms": 700, "cost_usd": 0.00044},
        # MiMo (subscription; cost=0)
        {"timestamp": "2026-05-25T10:04:00+00:00", "task_id": "t5",
         "engine": "mimo", "model": "mimo-v2.5-pro",
         "input_tokens": 1000, "output_tokens": 500,
         "latency_ms": 2000, "cost_usd": 0.0},
    ]
    p = tmp_path / "multi.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                 encoding="utf-8")
    return p


# -- shape contract ------------------------------------------------------


def test_budget_status_returns_dict_with_required_keys(empty_ledger):
    result = harness.budget_status(ledger_path=empty_ledger)
    required = {
        "session_tokens_total", "session_cost_total", "offload_ratio",
        "remaining_budget_usd", "dispatches_fired", "engines_used",
        "avg_cost_per_token", "cost_max_per_session_usd",
    }
    assert isinstance(result, dict)
    assert required <= set(result.keys()), (
        f"missing keys: {required - set(result.keys())}"
    )


# -- empty-ledger zero-state ---------------------------------------------


def test_budget_status_empty_ledger_returns_zeros(empty_ledger):
    result = harness.budget_status(ledger_path=empty_ledger)
    assert result["session_tokens_total"] == 0
    assert result["session_cost_total"] == 0.0
    assert result["dispatches_fired"] == 0
    assert result["engines_used"] == {}
    assert result["avg_cost_per_token"] == 0.0
    assert result["offload_ratio"] == 0.0


def test_budget_status_empty_ledger_does_not_crash():
    """Important: even with no ledger file at all, function returns
    a valid dict (not raise)."""
    result = harness.budget_status(ledger_path=Path("/nonexistent/path.jsonl"))
    assert isinstance(result, dict)
    assert result["session_tokens_total"] == 0


# -- populated ledger ----------------------------------------------------


def test_budget_status_counts_total_tokens(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    # Total: kimi (100+200) + (200+300) + deepseek (500+1000) + (300+800) + mimo (1000+500)
    expected_total = 300 + 500 + 1500 + 1100 + 1500
    assert result["session_tokens_total"] == expected_total


def test_budget_status_sums_cost(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    expected_cost = 0.0006 + 0.00044  # only deepseek had cost
    assert abs(result["session_cost_total"] - expected_cost) < 1e-6


def test_budget_status_counts_dispatches(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    assert result["dispatches_fired"] == 5


def test_budget_status_engines_used_breakdown(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    assert result["engines_used"] == {"kimi": 2, "deepseek": 2, "mimo": 1}


# -- offload_ratio (the load-bearing metric) -----------------------------


def test_budget_status_offload_ratio_all_subscription_is_1_0(tmp_path):
    """Ledger with only Kimi entries -> offload_ratio = 1.0."""
    entries = [
        {"timestamp": "2026-05-25T10:00:00+00:00", "task_id": "t",
         "engine": "kimi", "model": "kimi-k2.6",
         "input_tokens": 100, "output_tokens": 200,
         "latency_ms": 0, "cost_usd": 0.0},
    ]
    p = tmp_path / "kimi.jsonl"
    p.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
    result = harness.budget_status(ledger_path=p)
    assert result["offload_ratio"] == 1.0


def test_budget_status_offload_ratio_all_paid_is_0_0(tmp_path):
    """Ledger with only DeepSeek entries -> offload_ratio = 0.0."""
    entries = [
        {"timestamp": "2026-05-25T10:00:00+00:00", "task_id": "t",
         "engine": "deepseek", "model": "deepseek-v4-flash",
         "input_tokens": 100, "output_tokens": 200,
         "latency_ms": 0, "cost_usd": 0.0001},
    ]
    p = tmp_path / "ds.jsonl"
    p.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
    result = harness.budget_status(ledger_path=p)
    assert result["offload_ratio"] == 0.0


def test_budget_status_offload_ratio_mixed(multi_engine_ledger):
    """Subscription tokens / (sub + paid).
    sub: kimi (300+500) + mimo (1500) = 2300
    paid: deepseek (1500+1100) = 2600
    offload = 2300 / (2300+2600) = 0.4694"""
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    assert 0.45 < result["offload_ratio"] < 0.50


def test_budget_status_offload_ratio_in_range_0_to_1(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    assert 0.0 <= result["offload_ratio"] <= 1.0


# -- avg_cost_per_token --------------------------------------------------


def test_avg_cost_per_token_zero_when_no_tokens(empty_ledger):
    result = harness.budget_status(ledger_path=empty_ledger)
    assert result["avg_cost_per_token"] == 0.0


def test_avg_cost_per_token_correct_for_paid(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    # avg = total_cost / total_tokens
    # = 0.00104 / 4900 ≈ 2.12e-7
    assert 1e-7 < result["avg_cost_per_token"] < 1e-6


# -- remaining_budget_usd ------------------------------------------------


def test_remaining_budget_default_5_dollars(empty_ledger, monkeypatch):
    monkeypatch.delenv("COST_MAX_PER_SESSION", raising=False)
    result = harness.budget_status(ledger_path=empty_ledger)
    assert result["cost_max_per_session_usd"] == 5.0
    assert result["remaining_budget_usd"] == 5.0


def test_remaining_budget_decreases_with_spend(multi_engine_ledger):
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    assert result["remaining_budget_usd"] < result["cost_max_per_session_usd"]
    # Specifically: spent 0.00104 of $5
    assert abs(result["remaining_budget_usd"] - (5.0 - 0.00104)) < 1e-6


def test_remaining_budget_respects_env_override(empty_ledger, monkeypatch):
    monkeypatch.setenv("COST_MAX_PER_SESSION", "10.00")
    result = harness.budget_status(ledger_path=empty_ledger)
    assert result["cost_max_per_session_usd"] == 10.0
    assert result["remaining_budget_usd"] == 10.0


def test_remaining_budget_can_go_negative(tmp_path, monkeypatch):
    """If spend exceeded the cap, remaining is negative (operator-visible)."""
    monkeypatch.setenv("COST_MAX_PER_SESSION", "0.0001")
    entries = [
        {"timestamp": "2026-05-25T10:00:00+00:00", "task_id": "t",
         "engine": "deepseek", "model": "deepseek-v4-flash",
         "input_tokens": 1000, "output_tokens": 1000,
         "latency_ms": 0, "cost_usd": 0.50},
    ]
    p = tmp_path / "over.jsonl"
    p.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
    result = harness.budget_status(ledger_path=p)
    assert result["remaining_budget_usd"] < 0


def test_remaining_budget_invalid_env_falls_back_to_5(empty_ledger, monkeypatch):
    monkeypatch.setenv("COST_MAX_PER_SESSION", "not-a-number")
    result = harness.budget_status(ledger_path=empty_ledger)
    assert result["cost_max_per_session_usd"] == 5.0


# -- since_hours window --------------------------------------------------


def test_budget_status_since_hours_filters_old_entries(tmp_path):
    """Entries before the window cutoff are excluded."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=48)).isoformat()
    recent = (now - timedelta(minutes=10)).isoformat()
    entries = [
        {"timestamp": old, "task_id": "t1", "engine": "kimi",
         "model": "x", "input_tokens": 1, "output_tokens": 1,
         "latency_ms": 0, "cost_usd": 0.0},
        {"timestamp": recent, "task_id": "t2", "engine": "kimi",
         "model": "x", "input_tokens": 100, "output_tokens": 100,
         "latency_ms": 0, "cost_usd": 0.0},
    ]
    p = tmp_path / "windowed.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                 encoding="utf-8")
    # since_hours=24 -> only the recent entry counted
    result = harness.budget_status(ledger_path=p, since_hours=24.0)
    assert result["dispatches_fired"] == 1
    assert result["session_tokens_total"] == 200


def test_budget_status_since_hours_none_includes_all(multi_engine_ledger):
    """since_hours=None (default) = entire ledger."""
    result = harness.budget_status(ledger_path=multi_engine_ledger,
                                    since_hours=None)
    assert result["dispatches_fired"] == 5
    assert result["window_hours"] is None


# -- The agent's intended workflow --------------------------------------


def test_agent_can_poll_repeatedly_without_side_effects(multi_engine_ledger):
    """The agent polls budget_status() between dispatches.  Repeat
    calls must produce identical results (idempotent + side-effect-free)."""
    r1 = harness.budget_status(ledger_path=multi_engine_ledger)
    r2 = harness.budget_status(ledger_path=multi_engine_ledger)
    assert r1 == r2


def test_budget_status_payload_size_small(multi_engine_ledger):
    """Per panel C4 risk: telemetry must stay small or it accumulates
    in agent context across polls.  Target: <2KB serialized."""
    import json as _json
    result = harness.budget_status(ledger_path=multi_engine_ledger)
    serialized = _json.dumps(result)
    assert len(serialized) < 2000, (
        f"budget_status payload {len(serialized)} bytes — too big "
        f"for poll-friendly use"
    )
