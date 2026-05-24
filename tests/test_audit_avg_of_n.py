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


# -- W9-AUDIT-ANCHOR-MULTI-COMMIT ------------------------------------------


def test_resolve_commit_range_single_sha_returns_one_entry(monkeypatch):
    """A single SHA should round-trip to a 1-entry list via rev-parse."""
    captured: list[list[str]] = []

    def _fake(args, **kw):
        captured.append(list(args))
        class _R:
            stdout = "abc1234567890" if "rev-parse" in args else ""
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    shas = audit.resolve_commit_range("abc1234")
    assert shas == ["abc1234567890"]
    assert ["git", "rev-parse", "abc1234"] in captured


def test_resolve_commit_range_range_syntax_returns_oldest_first(monkeypatch):
    """A..B should invoke git log --reverse + return list oldest first."""
    captured: list[list[str]] = []

    def _fake(args, **kw):
        captured.append(list(args))
        class _R:
            stdout = "sha1\nsha2\nsha3\n"
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    shas = audit.resolve_commit_range("abc..def")
    assert shas == ["sha1", "sha2", "sha3"]
    # Verify --reverse was passed for oldest-first ordering
    last_call = captured[-1]
    assert "--reverse" in last_call
    assert "abc..def" in last_call


def test_resolve_commit_range_since_n(monkeypatch):
    """since:N should call git log -n N + reverse the output."""
    def _fake(args, **kw):
        class _R:
            stdout = "newsha\nmidsha\noldsha\n"  # log newest-first
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    shas = audit.resolve_commit_range("since:3")
    # Reversed: oldest first
    assert shas == ["oldsha", "midsha", "newsha"]


def test_resolve_commit_range_since_invalid_returns_empty(monkeypatch):
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": ""})())
    assert audit.resolve_commit_range("since:notanumber") == []
    assert audit.resolve_commit_range("since:0") == []
    assert audit.resolve_commit_range("since:-3") == []


def test_resolve_commit_range_caps_at_20(monkeypatch):
    """Both since:N and A..B path should cap result at 20 SHAs."""
    long_output = "\n".join(f"sha{i:04d}" for i in range(50)) + "\n"
    monkeypatch.setattr(
        audit.subprocess, "run",
        lambda args, **kw: type("R", (), {"stdout": long_output})(),
    )
    shas_range = audit.resolve_commit_range("a..b")
    assert len(shas_range) == 20


def test_git_commits_info_single_sha_falls_back_to_legacy(monkeypatch):
    """git_commit_info(sha) should delegate to git_commits_info([sha])."""
    captured: list[list[str]] = []

    def _fake(args, **kw):
        captured.append(list(args))
        class _R:
            if "rev-parse" in args:
                stdout = "abc123456789"
            elif "show" in args and "--no-patch" in args:
                stdout = "abc123456789\nClaude\n2026-05-24\ntest subject\n\ntest body"
            elif "--stat" in args:
                stdout = " file.py | 1 +\n"
            elif "--name-only" in args:
                stdout = "src/foo.py\n"
            else:
                stdout = "diff --git a/src/foo.py b/src/foo.py\n"
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    info = audit.git_commit_info("abc123")
    assert info["sha"] == "abc123456789"
    assert "Claude" == info["author"]
    assert info["diff_excerpt"]


def test_git_commits_info_multi_commit_aggregates_diffs(monkeypatch):
    """Two-commit deliverable should produce a diff with both commit
    delimiters present + a multi-commit message header."""
    call_counter = {"i": 0}

    def _fake(args, **kw):
        i = call_counter["i"]
        call_counter["i"] += 1
        class _R:
            stdout = ""
        # The new flow does rev-parse for each input SHA first
        if "rev-parse" in args:
            sha_arg = args[2]
            _R.stdout = sha_arg + "_full"
            return _R()
        if "show" in args and "--no-patch" in args and "--format=%H%n" in args[3]:
            _R.stdout = "sha1_full\nClaude\n2026-05-24\nfirst subject\n\nbody"
            return _R()
        if "show" in args and "--no-patch" in args and "--format=%s" in args[3]:
            sha = args[-1]
            _R.stdout = f"subj for {sha}"
            return _R()
        if "show" in args and "--stat" in args:
            sha = args[-1]
            _R.stdout = f" file_{sha[:4]}.py | 1 +\n"
            return _R()
        if "show" in args and "--name-only" in args:
            sha = args[-1]
            _R.stdout = f"src/file_{sha[:4]}.py\n"
            return _R()
        # default: bare git show for diff
        sha = args[-1]
        _R.stdout = f"diff --git a/src/file_{sha[:4]}.py b/src/file_{sha[:4]}.py\n"
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    info = audit.git_commits_info(["sha1", "sha2"])
    # Two-commit message includes the "multi-commit deliverable" header
    assert "multi-commit deliverable" in info["message"]
    assert "2 commits" in info["message"]
    # Diff contains both commit delimiters
    assert "commit sha1_full" in info["diff_excerpt"]
    assert "commit sha2_full" in info["diff_excerpt"]


def test_git_commits_info_dedupes_files_across_commits(monkeypatch):
    """If two commits touch the same file, the file_contents block
    should show that file once, not twice."""
    def _fake(args, **kw):
        class _R:
            stdout = ""
        if "rev-parse" in args:
            _R.stdout = args[2] + "_full"
            return _R()
        if "show" in args and "--no-patch" in args:
            _R.stdout = "sha_full\nClaude\n2026-05-24\nsubj\n\nbody"
            return _R()
        if "show" in args and "--stat" in args:
            _R.stdout = " file.py | 1 +\n"
            return _R()
        if "show" in args and "--name-only" in args:
            # Same file in both commits
            _R.stdout = "src/duplicated.py\n"
            return _R()
        _R.stdout = "diff content\n"
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    info = audit.git_commits_info(["sha1", "sha2"])
    # Only one file_contents block even though it was touched twice
    # (we can't directly read modified_files but file_contents should
    # have one ## src/duplicated.py header at most)
    content = info["file_contents"]
    # If the file exists on disk: count headers; if not: file_contents is "(none)"
    assert content.count("## src/duplicated.py") <= 1


def test_git_commits_info_empty_falls_back_to_HEAD(monkeypatch):
    """Empty SHA list defaults to ['HEAD'] for legacy safety."""
    calls: list[list[str]] = []

    def _fake(args, **kw):
        calls.append(list(args))
        class _R:
            stdout = "HEAD_RESOLVED"
        return _R()

    monkeypatch.setattr(audit.subprocess, "run", _fake)
    audit.git_commits_info([])
    # First call should rev-parse HEAD
    assert any("HEAD" in c and "rev-parse" in c for c in calls)


# -- W10-AUDIT-FOLLOWUP-COMMIT-POLICY -------------------------------------


def test_find_latest_commit_returns_first_match(monkeypatch):
    """Scan git log for the most recent commit subject containing task_id."""
    git_log = (
        "abc1234567 W10-FOO followup: address audit gap\n"
        "def4567890 W10-FOO original: initial implementation\n"
        "ghi7890123 W9-BAR: unrelated\n"
    )
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": git_log})())
    result = audit.find_latest_commit_for_task("W10-FOO")
    assert result == "abc1234567"


def test_find_latest_commit_returns_none_when_no_match(monkeypatch):
    git_log = (
        "abc1234567 W9-BAZ: unrelated commit\n"
        "def4567890 OTHER: another commit\n"
    )
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": git_log})())
    assert audit.find_latest_commit_for_task("W10-FOO") is None


def test_find_latest_commit_respects_token_boundary(monkeypatch):
    """W10-FO must NOT match W10-FOO (substring without boundary)."""
    git_log = "abc1234567 W10-FOO bar baz\n"
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": git_log})())
    # Searching for "W10-FO" should NOT match "W10-FOO" — the F at the
    # match end is alphanumeric, so the boundary check rejects.
    result = audit.find_latest_commit_for_task("W10-FO")
    # Actually the function allows hyphen-suffixed matches by design
    # (W10-CLI matches W10-CLI-TIMEOUT-BUDGET), but pure alpha-suffix
    # should be rejected.
    assert result is None


def test_find_latest_commit_allows_hyphen_suffix(monkeypatch):
    """A commit with W10-CLI-TIMEOUT-BUDGET should match W10-CLI searches.

    Many followup commits append a suffix; the function permits that
    because hyphen is a valid id-character.
    """
    git_log = "abc1234567 W10-CLI-TIMEOUT-BUDGET: fix\n"
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": git_log})())
    # NOTE: per the implementation note, hyphen-suffixed matches ARE
    # accepted (W10-CLI matches W10-CLI-TIMEOUT-BUDGET).  This is by
    # design — followup commits often append a suffix.
    result = audit.find_latest_commit_for_task("W10-CLI")
    assert result == "abc1234567"


def test_find_latest_commit_handles_empty_log(monkeypatch):
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": ""})())
    assert audit.find_latest_commit_for_task("W10-FOO") is None


def test_find_latest_commit_skips_substring_in_other_id(monkeypatch):
    """Boundary check: 'W10-FOO' should NOT match a commit named
    'XW10-FOO' (the X means it's part of a longer id, not a clean match)."""
    git_log = "abc1234567 XW10-FOO bar\n"
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": git_log})())
    assert audit.find_latest_commit_for_task("W10-FOO") is None
