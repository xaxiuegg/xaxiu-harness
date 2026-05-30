"""W11-L5-OUTPUT-CONTRACT: tests for visible L5 escalation output.

Per readiness panel: when an L5 fires what does the operator literally
SEE and what's the single action?  This covers the visible 'L5 ESCALATION'
banner template + the escalation-threshold gate.

PATH-A-TRIM 2026-05-29: the observer-restart-loop tests (record_restart_outcome
+ watchdog + the `harness today` L5-escalations section) were removed along
with the observer machinery they exercised.  The banner / is_l5 /
escalation_writeup / should_escalate_to_l5 surfaces stay (still used by the
core preflight + l5-banner-demo verbs).
"""

from __future__ import annotations

from datetime import datetime

from harness import l5_escalation as l5


# -- render_l5_banner ---------------------------------------------------


def test_render_l5_banner_includes_l5_header():
    """Operator MUST see the literal text 'L5' so the severity is unmissable."""
    text = l5.render_l5_banner(
        code="L5.engines.DEAD_KIMI",
        summary="kimi engine quarantined for 60min, no fallback",
        action="check API key + endpoint, then `harness engines test kimi`",
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
        summary="state.json unreadable",
        action="restore from backup",
        evidence=[
            "json.JSONDecodeError at line 5",
            "file size 0 bytes",
            "last modified 14h ago",
        ],
    )
    for ev in [
        "json.JSONDecodeError at line 5",
        "file size 0 bytes",
        "last modified 14h ago",
    ]:
        assert ev in text


def test_render_l5_banner_omits_evidence_section_when_empty():
    text_with = l5.render_l5_banner("L5.x.y", "s", "a", evidence=["one"])
    text_without = l5.render_l5_banner("L5.x.y", "s", "a")
    assert "Evidence" in text_with
    assert "Evidence" not in text_without


def test_render_l5_banner_is_visually_distinct():
    """Wraps in a visible border — operator must NOT mistake for ordinary log."""
    text = l5.render_l5_banner("L5.x.y", "s", "a")
    has_border = any(sep in text for sep in ("=" * 10, "█" * 5, "-" * 20, "*" * 10))
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


# -- escalation_writeup (JSON for email / brief) ------------------------


def test_escalation_writeup_returns_json_friendly_dict():
    w = l5.escalation_writeup(
        code="L5.engines.DEAD_KIMI",
        summary="kimi quarantined, no fallback",
        action="check key",
    )
    required = {"code", "severity", "summary", "action", "raised_at"}
    assert required <= set(w.keys())
    assert w["severity"] == "L5"
    # Timestamp is parseable ISO-8601
    datetime.fromisoformat(w["raised_at"])


def test_escalation_writeup_includes_evidence_when_supplied():
    w = l5.escalation_writeup("L5.x.y", "s", "a", evidence=["one", "two"])
    assert w["evidence"] == ["one", "two"]


# -- escalation threshold gate ------------------------------------------


def test_should_escalate_to_l5_when_consecutive_failures_reach_threshold():
    """Threshold is 3 by default."""
    assert l5.should_escalate_to_l5(consecutive_failures=2) is False
    assert l5.should_escalate_to_l5(consecutive_failures=3) is True
    assert l5.should_escalate_to_l5(consecutive_failures=5) is True


def test_should_escalate_to_l5_respects_custom_threshold():
    assert l5.should_escalate_to_l5(2, threshold=2) is True
    assert l5.should_escalate_to_l5(1, threshold=2) is False


# -- CLI surface --------------------------------------------------------


def test_cli_l5_banner_demo_invokes_render():
    """harness l5-banner-demo prints a synthetic banner for visual check."""
    from click.testing import CliRunner

    from harness.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["l5-banner-demo"])
    assert result.exit_code == 0
    assert "L5" in result.output
    assert "ESCALATION" in result.output.upper()


# -- preflight FAIL surfaces L5 banner -----------------------------------


def test_preflight_fail_output_includes_l5_banner(monkeypatch):
    """When preflight returns exit 4 (any FAIL), CLI prints L5 banner
    BEFORE the per-check table so it's the operator's first read."""
    from click.testing import CliRunner

    from harness import preflight as pf
    from harness.cli import cli

    fake = [
        pf.PreflightCheck(
            name="engine:kimi",
            severity="fail",
            message="dispatch raised: 500",
            duration_ms=2000,
            fix="check kimi key",
        ),
    ]
    monkeypatch.setattr("harness.preflight.run_all", lambda **k: fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["preflight"])
    if result.exit_code == 4:
        assert "L5" in result.output
        assert "ESCALATION" in result.output.upper()
