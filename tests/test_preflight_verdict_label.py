"""W10-PREFLIGHT-EXIT-CODE-SEMANTICS: verdict-label translation tests.

The non-technical operator historically reads "exit 1" as FAIL when
the harness intends "warning, still ok to proceed".  The new
verdict_label helper translates exit codes into plain-language
(short_verdict, explanation) pairs that the CLI prints after the
per-check listing.

Tests cover:
  - Pure translation of each known exit code
  - Unknown exit codes don't crash
  - CLI integration prints the verdict line
  - overall_exit_code semantics unchanged (regression-protect CI
    scripts that depend on the integer values)
"""

from __future__ import annotations



from harness.preflight import (
    PreflightCheck,
    overall_exit_code,
    verdict_label,
)


# -- verdict_label translation --------------------------------------------


def test_verdict_label_zero_is_pass():
    label, explanation = verdict_label(0)
    assert label == "PASS"
    assert "ready" in explanation.lower()


def test_verdict_label_one_is_pass_with_warnings():
    label, explanation = verdict_label(1)
    assert label == "PASS-WITH-WARNINGS"
    # Critical for the operator: they need to KNOW exit 1 is still ok
    assert "proceed" in explanation.lower() or "actionable" in explanation.lower()


def test_verdict_label_four_is_fail():
    label, explanation = verdict_label(4)
    assert label == "FAIL"
    assert "blocker" in explanation.lower() or "refuses" in explanation.lower()


def test_verdict_label_unknown_is_marked_unknown():
    """Defensive: exit code 7 (say, future) should not crash."""
    label, explanation = verdict_label(7)
    assert label == "UNKNOWN"
    assert "7" in explanation


def test_verdict_label_negative_is_marked_unknown():
    label, explanation = verdict_label(-1)
    assert label == "UNKNOWN"


# -- overall_exit_code semantics preserved --------------------------------


def _mk(severity: str) -> PreflightCheck:
    return PreflightCheck(name="x", severity=severity, message="m")


def test_overall_exit_code_all_ok_is_zero():
    assert overall_exit_code([_mk("ok"), _mk("ok")]) == 0


def test_overall_exit_code_warn_is_one():
    assert overall_exit_code([_mk("ok"), _mk("warn")]) == 1


def test_overall_exit_code_fail_is_four():
    """Fail dominates warn."""
    assert overall_exit_code([_mk("warn"), _mk("fail")]) == 4


def test_overall_exit_code_empty_is_zero():
    """No checks = all ok."""
    assert overall_exit_code([]) == 0


# -- CLI integration: verdict line printed --------------------------------








