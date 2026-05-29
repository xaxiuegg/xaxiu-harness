"""Tests for the cross-vendor MCP server tool functions.

The dispatch layer is MOCKED — these tests make ZERO real engine calls.
They pin the tool return shapes + confirm the module imports without the
``mcp`` SDK (the FastMCP wiring is lazy-imported).
"""
import pytest

from harness import ask
from harness.ask import AskResult, AuditOutcome
import harness.mcp_server as mcp_server


def _ar(engine: str, text: str = "ok", cost: float = 0.01,
        okay: bool = True) -> AskResult:
    return AskResult(
        engine=engine, ok=okay, elapsed_s=1.0, tokens_in=10, tokens_out=20,
        cost_usd=cost, text=text, error="" if okay else "boom",
        winning_alias=engine, attempt_count=1,
    )


def test_module_imports_without_mcp_sdk():
    # Importing must not require the mcp SDK (lazy in build_server).
    assert callable(mcp_server.cross_vendor_audit)
    assert callable(mcp_server.cross_vendor_panel)
    assert callable(mcp_server.main)


def test_cross_vendor_audit_shape(monkeypatch):
    def fake_run_audit(question, producer_engine, **kw):
        prod = _ar(producer_engine, "the answer")
        aud = _ar("deepseek-via-claude", "audit text")
        return AuditOutcome(
            producer=prod, auditor=aud, auditor_engine="deepseek-via-claude",
            verdict={"verdict": "PASS", "summary": "looks right",
                     "corrections": "none", "missed": "none"},
            auditors=[aud], auditor_engines=["deepseek-via-claude"],
            verdicts=[{"verdict": "PASS"}],
        )
    monkeypatch.setattr(ask, "run_audit", fake_run_audit)

    out = mcp_server.cross_vendor_audit(
        "is X true?", producer_engine="mimo-via-claude",
    )
    assert out["verdict"] == "PASS"
    assert out["producer_engine"] == "mimo-via-claude"
    assert out["auditor_engines"] == ["deepseek-via-claude"]
    assert out["audited"] is True
    assert out["producer_ok"] is True
    assert out["total_cost_usd"] == pytest.approx(0.02)
    expected_keys = {
        "verdict", "summary", "corrections", "missed", "producer_engine",
        "producer_ok", "producer_answer", "auditor_engines", "audited",
        "total_cost_usd",
    }
    assert expected_keys.issubset(out)


def test_cross_vendor_audit_producer_failure(monkeypatch):
    def fake_run_audit(question, producer_engine, **kw):
        prod = _ar(producer_engine, "", okay=False)
        return AuditOutcome(
            producer=prod, auditor=None, auditor_engine="", verdict=None,
            auditors=[], auditor_engines=[], verdicts=[],
        )
    monkeypatch.setattr(ask, "run_audit", fake_run_audit)

    out = mcp_server.cross_vendor_audit("q", producer_engine="mimo-via-claude")
    assert out["verdict"] == "UNKNOWN"
    assert out["audited"] is False
    assert out["producer_ok"] is False


def test_cross_vendor_panel_shape(monkeypatch):
    def fake_run_panel(question, *args, **kw):
        return [
            _ar("kimi-via-claude", "k"),
            _ar("mimo-via-claude", "m"),
            _ar("deepseek-via-claude", "d", okay=False),
        ]
    monkeypatch.setattr(ask, "run_panel", fake_run_panel)

    out = mcp_server.cross_vendor_panel("compare X")
    assert len(out["engines"]) == 3
    assert out["engines"][0]["engine"] == "kimi-via-claude"
    assert out["engines"][0]["ok"] is True
    assert out["engines"][2]["ok"] is False
    assert out["engines"][2]["answer"] == ""        # failed engine: no answer
    assert out["total_cost_usd"] == pytest.approx(0.03)


def test_resolve_producer_explicit():
    assert mcp_server._resolve_producer("kimi-via-claude") == "kimi-via-claude"


def test_resolve_producer_default_is_nonempty():
    # No explicit producer → recommender pick or the mimo fallback; never empty.
    assert mcp_server._resolve_producer("") != ""


def test_build_server_when_mcp_available():
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    assert server is not None
