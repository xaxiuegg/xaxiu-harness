"""W9-AUDIT-NONDETERMINISM-AVG: regression tests for the --avg-of-N flag
on scripts/audit_task_with_mimo.py.

These tests target the pure helpers (aggregation, parsing, formatting,
gate logic) without hitting MiMo or git.  The end-to-end flow is
exercised by the existing audit_wave8_all.py + manual sweeps.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import the script as a module (it lives in scripts/, not src/).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_task_with_mimo.py"
_spec = importlib.util.spec_from_file_location("audit_task_with_mimo", _SCRIPT)
audit = importlib.util.module_from_spec(_spec)
sys.modules["audit_task_with_mimo"] = audit
_spec.loader.exec_module(audit)


# -- parse_audit_response --------------------------------------------------


def test_parse_audit_response_extracts_json():
    text = """\
Some preamble that MiMo sometimes emits before the JSON.

{
  "task_id": "W9-FOO",
  "criteria_met": true,
  "confidence": 0.85,
  "verdict": "PASS",
  "one_line_summary": "Looks good"
}
"""
    conf, verdict, parsed = audit.parse_audit_response(text)
    assert conf == 0.85
    assert verdict == "PASS"
    assert parsed["task_id"] == "W9-FOO"
    assert parsed["criteria_met"] is True


def test_parse_audit_response_returns_zero_on_garbage():
    conf, verdict, parsed = audit.parse_audit_response("MiMo refused to respond")
    assert conf == 0.0
    assert verdict == "?"
    assert parsed == {}


def test_parse_audit_response_returns_zero_on_empty():
    conf, verdict, parsed = audit.parse_audit_response("")
    assert conf == 0.0
    assert verdict == "?"
    assert parsed == {}


def test_parse_audit_response_handles_invalid_json():
    """A response with braces but not valid JSON should fail cleanly."""
    text = '{this is "not" valid: json,,,}'
    conf, verdict, parsed = audit.parse_audit_response(text)
    assert conf == 0.0
    assert verdict == "?"
    assert parsed == {}


# -- aggregate_runs --------------------------------------------------------


def _mk(conf: float, verdict: str = "PASS", success: bool = True,
        error: str | None = None) -> "audit.AuditRun":
    return audit.AuditRun(
        confidence=conf,
        verdict=verdict,
        text=f"canned text for conf={conf}",
        parsed={"confidence": conf, "verdict": verdict},
        latency_ms=100,
        auditor_used="mimo",
        success=success,
        error=error,
    )


def test_aggregate_single_run_mean_equals_value():
    summary = audit.aggregate_runs([_mk(0.75)])
    assert summary.total_runs == 1
    assert summary.successful_runs == 1
    assert summary.mean_confidence == 0.75
    assert summary.stdev_confidence == 0.0  # N<2 = 0
    assert summary.min_confidence == 0.75
    assert summary.max_confidence == 0.75
    assert summary.pass_count == 1
    assert summary.passed


def test_aggregate_three_runs_nondeterministic_pass_fail_pass():
    """The W8 case: 0.85 / 0.40 / 0.85 — mean is 0.70 which is ON the gate."""
    runs = [_mk(0.85), _mk(0.40, verdict="STOP"), _mk(0.85)]
    summary = audit.aggregate_runs(runs)
    assert summary.total_runs == 3
    assert summary.successful_runs == 3
    assert summary.mean_confidence == pytest.approx(0.7, abs=0.001)
    assert summary.stdev_confidence > 0.0  # real variance
    assert summary.min_confidence == 0.40
    assert summary.max_confidence == 0.85
    assert summary.pass_count == 2  # 2 of 3 individually passed
    assert summary.passed  # mean exactly on gate


def test_aggregate_mean_below_gate_stops():
    """Three runs all below gate: mean < 0.7 → STOP."""
    runs = [_mk(0.60, verdict="STOP"), _mk(0.55, verdict="STOP"), _mk(0.50, verdict="STOP")]
    summary = audit.aggregate_runs(runs)
    assert summary.mean_confidence == pytest.approx(0.55, abs=0.001)
    assert summary.pass_count == 0
    assert not summary.passed


def test_aggregate_mean_well_above_gate_passes():
    runs = [_mk(0.90), _mk(0.85), _mk(0.95)]
    summary = audit.aggregate_runs(runs)
    assert summary.mean_confidence == pytest.approx(0.90, abs=0.001)
    assert summary.pass_count == 3
    assert summary.passed


def test_aggregate_all_failed_runs_returns_zero_and_stops():
    runs = [
        _mk(0.0, verdict="?", success=False, error="MiMo down"),
        _mk(0.0, verdict="?", success=False, error="DeepSeek down"),
    ]
    summary = audit.aggregate_runs(runs)
    assert summary.successful_runs == 0
    assert summary.mean_confidence == 0.0
    assert summary.pass_count == 0
    assert not summary.passed


def test_aggregate_partial_failure_uses_only_successful_runs():
    """If 2/3 runs succeed, the mean is over the 2 successful only."""
    runs = [
        _mk(0.80),
        _mk(0.0, verdict="?", success=False, error="timeout"),
        _mk(0.90),
    ]
    summary = audit.aggregate_runs(runs)
    assert summary.successful_runs == 2
    assert summary.total_runs == 3
    assert summary.mean_confidence == pytest.approx(0.85, abs=0.001)
    assert summary.passed


def test_aggregate_empty_runs_returns_zero_and_stops():
    summary = audit.aggregate_runs([])
    assert summary.total_runs == 0
    assert summary.successful_runs == 0
    assert summary.mean_confidence == 0.0
    assert not summary.passed


# -- _format_avg_report ----------------------------------------------------


def test_format_avg_report_contains_header_and_per_run_blocks():
    runs = [_mk(0.80), _mk(0.60, verdict="STOP"), _mk(0.90)]
    summary = audit.aggregate_runs(runs)
    info = {
        "sha": "abcdef0123456789",
        "author": "Claude",
        "date": "2026-05-24",
        "message": "test commit\n\nbody text",
    }
    body = audit._format_avg_report("W9-AUDIT-NONDETERMINISM-AVG", info, summary)
    # HTML comment with metrics
    assert "avg_of_n=3" in body
    assert "mean_confidence=0.77" in body  # (0.8+0.6+0.9)/3 = 0.766... -> 0.77 after :.2f
    assert "pass_count=2/3" in body
    # Per-run section appears
    assert "## Per-run details" in body
    assert "### Run 1" in body
    assert "### Run 2" in body
    assert "### Run 3" in body
    # Confidence shown per run
    assert "0.80" in body
    assert "0.60" in body
    assert "0.90" in body


def test_format_avg_report_marks_failed_runs():
    runs = [
        _mk(0.85),
        _mk(0.0, verdict="?", success=False, error="MiMo timeout"),
    ]
    summary = audit.aggregate_runs(runs)
    info = {"sha": "abc", "author": "x", "date": "2026-05-24", "message": "msg"}
    body = audit._format_avg_report("W9-X", info, summary)
    assert "FAILED" in body
    assert "MiMo timeout" in body


# -- _format_single_report -------------------------------------------------


def test_format_single_report_matches_legacy_shape():
    """N=1 report must remain backwards-compatible with old audit reports."""
    run = _mk(0.85, verdict="PASS")
    info = {
        "sha": "abcdef0123456789",
        "author": "Claude",
        "date": "2026-05-24",
        "message": "commit subject",
    }
    body = audit._format_single_report("W9-X", info, run)
    assert "# Wave 6 MiMo audit — task W9-X" in body
    assert "Confidence: **0.85**" in body
    assert "Verdict: **PASS**" in body
    assert "## Raw MiMo audit response" in body


# -- _resolve_outpath ------------------------------------------------------


def test_resolve_outpath_suffix_changes_for_avg():
    p1 = audit._resolve_outpath("W9-FOO", 1)
    p3 = audit._resolve_outpath("W9-FOO", 3)
    assert p1.name.endswith("_W9-FOO_audit.md")
    assert p3.name.endswith("_W9-FOO_audit_avg3.md")
    # Same parent dir
    assert p1.parent == p3.parent


# -- Plan path resolution ---------------------------------------------------


def test_resolve_plan_path_w9_routes_to_wave9_plan():
    path = audit._resolve_plan_path("W9-AUDIT-NONDETERMINISM-AVG", None)
    assert path == Path("spec/wave-9-plan.md")


def test_resolve_plan_path_w8_routes_to_wave8_plan():
    path = audit._resolve_plan_path("W8-STOP-HOOK", None)
    assert path == Path("spec/wave-8-plan.md")


def test_resolve_plan_path_w7_routes_to_wave7_plan():
    path = audit._resolve_plan_path("W7-CLOSEOUT", None)
    assert path == Path("spec/wave-7-plan.md")


def test_resolve_plan_path_override_wins():
    path = audit._resolve_plan_path("W9-FOO", "spec/custom-plan.md")
    assert path == Path("spec/custom-plan.md")
