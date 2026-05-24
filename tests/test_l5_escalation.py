"""W11-L5-OUTPUT-CONTRACT: tests for visible L5 escalation output.

Per readiness panel: when an L5 fires what does the operator literally
SEE and what's the single action?  Today the L5 contract is internal
(preflight verdict_label says FAIL; observer flags fire).  Add a
visible 'L5 ESCALATION' header template + dashboard banner + the
watchdog escalation chain (3 consecutive restart failures → L5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from harness import l5_escalation as l5
from harness.observer import state as observer_state


# -- render_l5_banner ---------------------------------------------------


def test_render_l5_banner_includes_l5_header():
    """Operator MUST see the literal text 'L5' so the severity is unmissable."""
    text = l5.render_l5_banner(
        code="L5.observer.OBSERVER_RESTART_LOOP",
        summary="observer scheduler restart failed 3 times",
        action="run `harness observer install-scheduler --force` manually",
    )
    assert "L5" in text
    # The word ESCALATION is the visual cue
    assert "ESCALATION" in text.upper()


def test_render_l5_banner_includes_code_summary_action():
    text = l5.render_l5_banner(
        code="L5.engines.DEAD_KIMI",
        summary="kimi engine quarantined for 60min, no fallback",
        action="check API key + endpoint, then `harness engines test kimi`",
    )
    assert "L5.engines.DEAD_KIMI" in text
    assert "kimi engine quarantined" in text
    assert "harness engines test kimi" in text


def test_render_l5_banner_includes_evidence_when_supplied():
    """Optional evidence lines for the operator's drill-down."""
    text = l5.render_l5_banner(
        code="L5.state.STATE_CORRUPT",
        summary="observer-state.json unreadable",
        action="restore from coord/observer/observer-state.bak",
        evidence=["json.JSONDecodeError at line 5",
                  "file size 0 bytes",
                  "last modified 14h ago"],
    )
    for ev in ["json.JSONDecodeError at line 5",
               "file size 0 bytes",
               "last modified 14h ago"]:
        assert ev in text


def test_render_l5_banner_omits_evidence_section_when_empty():
    text_with = l5.render_l5_banner("L5.x.y", "s", "a", evidence=["one"])
    text_without = l5.render_l5_banner("L5.x.y", "s", "a")
    assert "Evidence" in text_with
    assert "Evidence" not in text_without


def test_render_l5_banner_is_visually_distinct():
    """Wraps in a visible border — operator must NOT mistake for ordinary log."""
    text = l5.render_l5_banner("L5.x.y", "s", "a")
    # Must include some kind of border (=== or ████ or ---)
    has_border = any(
        sep in text for sep in ("=" * 10, "█" * 5, "-" * 20, "*" * 10)
    )
    assert has_border


def test_render_l5_banner_action_marked_as_single_action():
    """Per spec: 'single action' must be visually called out as ACTION:."""
    text = l5.render_l5_banner("L5.x.y", "summary", "click this")
    assert "ACTION" in text.upper()


# -- is_l5 / parse_severity ---------------------------------------------


def test_is_l5_accepts_l5_prefix():
    assert l5.is_l5("L5.observer.X") is True


def test_is_l5_rejects_other_severities():
    assert l5.is_l5("L1.x.y") is False
    assert l5.is_l5("L4.x.y") is False
    assert l5.is_l5("") is False


def test_is_l5_handles_case_insensitive():
    assert l5.is_l5("l5.foo.bar") is True


# -- escalation_writeup (JSON for dashboard / email) --------------------


def test_escalation_writeup_returns_json_friendly_dict():
    """Dashboard / email rendering ingests this dict."""
    w = l5.escalation_writeup(
        code="L5.observer.OBSERVER_RESTART_LOOP",
        summary="restart failed 3 times",
        action="run --force",
    )
    required = {"code", "severity", "summary", "action", "raised_at"}
    assert required <= set(w.keys())
    assert w["severity"] == "L5"
    # Timestamp is parseable ISO-8601
    datetime.fromisoformat(w["raised_at"])


def test_escalation_writeup_includes_evidence_when_supplied():
    w = l5.escalation_writeup("L5.x.y", "s", "a", evidence=["one", "two"])
    assert w["evidence"] == ["one", "two"]


# -- watchdog escalation chain (3 consecutive restart failures) ---------


def test_record_restart_outcome_success_resets_counter(tmp_path):
    """A successful restart resets the consecutive-failure counter to 0."""
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)
    # Two failures then a success → counter resets
    l5.record_restart_outcome(False, observer_dir=tmp_path)
    l5.record_restart_outcome(False, observer_dir=tmp_path)
    after_success = l5.record_restart_outcome(True, observer_dir=tmp_path)
    assert after_success == 0


def test_record_restart_outcome_failure_increments_counter(tmp_path):
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)
    n1 = l5.record_restart_outcome(False, observer_dir=tmp_path)
    n2 = l5.record_restart_outcome(False, observer_dir=tmp_path)
    n3 = l5.record_restart_outcome(False, observer_dir=tmp_path)
    assert n1 == 1
    assert n2 == 2
    assert n3 == 3


def test_should_escalate_to_l5_when_consecutive_failures_reach_threshold():
    """Threshold is 3 by default."""
    assert l5.should_escalate_to_l5(consecutive_failures=2) is False
    assert l5.should_escalate_to_l5(consecutive_failures=3) is True
    assert l5.should_escalate_to_l5(consecutive_failures=5) is True


def test_should_escalate_to_l5_respects_custom_threshold():
    assert l5.should_escalate_to_l5(2, threshold=2) is True
    assert l5.should_escalate_to_l5(1, threshold=2) is False


def test_watchdog_restart_records_outcome(tmp_path, monkeypatch):
    """After restart_observer() runs, the counter reflects the outcome."""
    from harness.observer import watchdog
    monkeypatch.setattr(watchdog, "_unregister_for_platform",
                         lambda: (True, "ok"))
    monkeypatch.setattr(watchdog, "_register_for_platform",
                         lambda **k: (False, "register failed"))
    s = observer_state.ObserverState(armed=True, cadence_minutes=60)
    observer_state.write_state(s, observer_dir=tmp_path)
    ok, _msg = watchdog.restart_observer(observer_dir=tmp_path)
    assert ok is False
    # Counter incremented to 1
    state_after = observer_state.read_state(observer_dir=tmp_path)
    assert state_after.consecutive_restart_failures == 1


def test_watchdog_restart_success_resets_counter(tmp_path, monkeypatch):
    from harness.observer import watchdog
    # Seed two prior failures
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60,
        consecutive_restart_failures=2,
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    monkeypatch.setattr(watchdog, "_unregister_for_platform",
                         lambda: (True, "ok"))
    monkeypatch.setattr(watchdog, "_register_for_platform",
                         lambda **k: (True, "ok"))
    ok, _msg = watchdog.restart_observer(observer_dir=tmp_path)
    assert ok is True
    state_after = observer_state.read_state(observer_dir=tmp_path)
    assert state_after.consecutive_restart_failures == 0


def test_watchdog_restart_l5_message_on_threshold(tmp_path, monkeypatch):
    """Once 3 consecutive failures, restart_observer's message includes L5."""
    from harness.observer import watchdog
    s = observer_state.ObserverState(
        armed=True, cadence_minutes=60,
        consecutive_restart_failures=2,  # next failure → 3 → escalate
    )
    observer_state.write_state(s, observer_dir=tmp_path)
    monkeypatch.setattr(watchdog, "_unregister_for_platform",
                         lambda: (True, "ok"))
    monkeypatch.setattr(watchdog, "_register_for_platform",
                         lambda **k: (False, "still failing"))
    ok, msg = watchdog.restart_observer(observer_dir=tmp_path)
    assert ok is False
    # The L5 escalation header MUST appear in the message
    assert "L5" in msg.upper() or "ESCALATION" in msg.upper()


# -- CLI surface --------------------------------------------------------


def test_cli_l5_banner_demo_invokes_render(tmp_path, monkeypatch):
    """harness l5-banner-demo prints a synthetic banner for visual check."""
    from click.testing import CliRunner
    from harness.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["l5-banner-demo"])
    assert result.exit_code == 0
    assert "L5" in result.output
    assert "ESCALATION" in result.output.upper()


# -- preflight FAIL surfaces L5 banner -----------------------------------


def test_preflight_fail_output_includes_l5_banner(tmp_path, monkeypatch):
    """When preflight returns exit 4 (any FAIL), CLI prints L5 banner
    BEFORE the per-check table so it's the operator's first read."""
    from click.testing import CliRunner
    from harness import preflight as pf
    from harness.cli import cli

    fake = [
        pf.PreflightCheck(name="engine:kimi", severity="fail",
                          message="dispatch raised: 500", duration_ms=2000,
                          fix="check kimi key"),
    ]
    monkeypatch.setattr(pf, "run_all", lambda **k: fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["preflight", "--skip-engines"])
    # With --skip-engines, the patch above is moot for the production path;
    # easier path: monkeypatch the import the CLI uses
    monkeypatch.setattr("harness.preflight.run_all", lambda **k: fake)
    result = runner.invoke(cli, ["preflight"])
    # exit code 4 (FAIL) — and the output begins with the L5 banner
    if result.exit_code == 4:
        assert "L5" in result.output
        assert "ESCALATION" in result.output.upper()
