"""W11-COST-VISIBILITY-WIDGET: tests for the operator-facing cost widget.

Per operator-UX panel U5 + master audit K09: operators expect cost
visibility like Claude/ChatGPT shows token counts.  This widget shows
'this session cost $X' without grepping ledgers.

Distinguishes tp- subscription (zero marginal cost) from sk- per-token
clearly so the operator never confuses "$0 paid" with "$0 work done".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness import cost_widget as cw


# -- helpers ------------------------------------------------------------


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + ("\n" if entries else ""),
        encoding="utf-8",
    )


@pytest.fixture
def empty_ledger(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def mixed_ledger(tmp_path):
    now = datetime.now(timezone.utc)
    entries = [
        # 2 kimi (subscription)
        {"timestamp": now.isoformat(), "task_id": "t1",
         "engine": "kimi", "model": "k", "input_tokens": 100,
         "output_tokens": 200, "latency_ms": 1000, "cost_usd": 0.0},
        {"timestamp": now.isoformat(), "task_id": "t2",
         "engine": "kimi", "model": "k", "input_tokens": 50,
         "output_tokens": 80, "latency_ms": 900, "cost_usd": 0.0},
        # 1 deepseek (paid)
        {"timestamp": now.isoformat(), "task_id": "t3",
         "engine": "deepseek", "model": "d", "input_tokens": 500,
         "output_tokens": 1000, "latency_ms": 800, "cost_usd": 0.0012},
    ]
    p = tmp_path / "mixed.jsonl"
    _write_ledger(p, entries)
    return p


# -- cost_widget_dict (the structured payload) --------------------------


def test_cost_widget_dict_returns_required_keys(mixed_ledger):
    w = cw.cost_widget_dict(ledger_path=mixed_ledger)
    required = {
        "spent_usd",                # dollars spent this window
        "budget_usd",               # the cap
        "remaining_usd",            # cap - spent
        "pct_of_budget_used",       # 0..1
        "offload_ratio",            # subscription / total
        "dispatches",               # total count
        "subscription_dispatches",  # of which from sub engines
        "paid_dispatches",          # of which from paid engines
        "window_label",             # "today" / "last 1h" etc.
        "status",                   # "ok" / "warn" / "exhausted"
    }
    assert required <= set(w.keys()), (
        f"missing: {required - set(w.keys())}"
    )


def test_cost_widget_dict_empty_ledger_zero_state(empty_ledger):
    w = cw.cost_widget_dict(ledger_path=empty_ledger)
    assert w["spent_usd"] == 0.0
    assert w["dispatches"] == 0
    assert w["subscription_dispatches"] == 0
    assert w["paid_dispatches"] == 0
    assert w["status"] == "ok"
    assert w["offload_ratio"] == 0.0


def test_cost_widget_dict_subscription_paid_breakdown(mixed_ledger):
    w = cw.cost_widget_dict(ledger_path=mixed_ledger)
    # 2 kimi + 1 deepseek
    assert w["dispatches"] == 3
    assert w["subscription_dispatches"] == 2
    assert w["paid_dispatches"] == 1
    # Spend = 0.0012 (only the deepseek call)
    assert abs(w["spent_usd"] - 0.0012) < 1e-6


def test_cost_widget_dict_status_warn_when_over_80pct(tmp_path, monkeypatch):
    """status='warn' when spend ≥ 80% of budget."""
    monkeypatch.setenv("COST_MAX_PER_SESSION", "0.01")
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "warn.jsonl"
    _write_ledger(p, [{
        "timestamp": now, "task_id": "t",
        "engine": "deepseek", "model": "d",
        "input_tokens": 1000, "output_tokens": 1000,
        "latency_ms": 0, "cost_usd": 0.009,  # 90% of $0.01
    }])
    w = cw.cost_widget_dict(ledger_path=p)
    assert w["status"] == "warn"
    assert w["pct_of_budget_used"] >= 0.8


def test_cost_widget_dict_status_exhausted_when_over_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("COST_MAX_PER_SESSION", "0.005")
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "over.jsonl"
    _write_ledger(p, [{
        "timestamp": now, "task_id": "t",
        "engine": "deepseek", "model": "d",
        "input_tokens": 1000, "output_tokens": 1000,
        "latency_ms": 0, "cost_usd": 0.01,
    }])
    w = cw.cost_widget_dict(ledger_path=p)
    assert w["status"] == "exhausted"
    assert w["remaining_usd"] < 0


def test_cost_widget_dict_status_ok_when_well_under_budget(mixed_ledger):
    w = cw.cost_widget_dict(ledger_path=mixed_ledger)
    assert w["status"] == "ok"


def test_cost_widget_dict_window_label_today(mixed_ledger):
    w = cw.cost_widget_dict(ledger_path=mixed_ledger, since_hours=24)
    assert w["window_label"] == "today" or "24" in w["window_label"]


def test_cost_widget_dict_window_label_all_time(mixed_ledger):
    w = cw.cost_widget_dict(ledger_path=mixed_ledger, since_hours=None)
    assert "all" in w["window_label"].lower() or "session" in w["window_label"].lower()


# -- format_cost_widget (the operator-readable text) --------------------


def test_format_cost_widget_includes_dollar_spent(mixed_ledger):
    text = cw.format_cost_widget(ledger_path=mixed_ledger)
    # Operator-readable cost line with $ sign
    assert "$" in text


def test_format_cost_widget_distinguishes_subscription_vs_paid(mixed_ledger):
    """Per spec: tp- (sub) vs sk- (paid) must be CLEARLY distinguished —
    operator must never confuse '$0 paid' with '$0 work done'."""
    text = cw.format_cost_widget(ledger_path=mixed_ledger)
    lower = text.lower()
    # Mentions both sides explicitly
    assert "subscription" in lower or "sub" in lower
    # Mentions paid/per-token side
    assert "paid" in lower or "per-token" in lower or "deepseek" in lower


def test_format_cost_widget_empty_ledger_is_friendly(empty_ledger):
    """Operator sees plain English, not a NaN or div-by-zero."""
    text = cw.format_cost_widget(ledger_path=empty_ledger)
    assert "$0" in text or "0.00" in text or "no dispatches" in text.lower()


def test_format_cost_widget_warn_text_visible_when_status_warn(tmp_path, monkeypatch):
    monkeypatch.setenv("COST_MAX_PER_SESSION", "0.01")
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "warn.jsonl"
    _write_ledger(p, [{
        "timestamp": now, "task_id": "t",
        "engine": "deepseek", "model": "d",
        "input_tokens": 1000, "output_tokens": 1000,
        "latency_ms": 0, "cost_usd": 0.0095,
    }])
    text = cw.format_cost_widget(ledger_path=p)
    # Warn signal: emoji-free but visible word
    assert "WARN" in text.upper() or "approaching" in text.lower() or "near" in text.lower()


def test_format_cost_widget_exhausted_text_visible_when_over(tmp_path, monkeypatch):
    monkeypatch.setenv("COST_MAX_PER_SESSION", "0.001")
    now = datetime.now(timezone.utc).isoformat()
    p = tmp_path / "over.jsonl"
    _write_ledger(p, [{
        "timestamp": now, "task_id": "t",
        "engine": "deepseek", "model": "d",
        "input_tokens": 1000, "output_tokens": 1000,
        "latency_ms": 0, "cost_usd": 0.01,
    }])
    text = cw.format_cost_widget(ledger_path=p)
    assert "EXHAUSTED" in text.upper() or "over" in text.lower() or "exceeded" in text.lower()


# -- size discipline (agent polls this) ---------------------------------


def test_cost_widget_dict_payload_is_compact(mixed_ledger):
    """Same poll-friendly contract as budget_status."""
    w = cw.cost_widget_dict(ledger_path=mixed_ledger)
    serialized = json.dumps(w)
    assert len(serialized) < 1000


def test_format_cost_widget_under_400_chars(mixed_ledger):
    """Single dashboard line: fits in a notification / status bar."""
    text = cw.format_cost_widget(ledger_path=mixed_ledger)
    assert len(text) < 400


# -- repeated calls are idempotent --------------------------------------


def test_cost_widget_dict_is_idempotent(mixed_ledger):
    a = cw.cost_widget_dict(ledger_path=mixed_ledger)
    b = cw.cost_widget_dict(ledger_path=mixed_ledger)
    assert a == b


# -- CLI surface --------------------------------------------------------


def test_cli_cost_today_command_exists():
    """harness cost-today must be a registered click command."""
    from harness.cli import cli
    assert "cost-today" in cli.commands or "budget" in cli.commands
