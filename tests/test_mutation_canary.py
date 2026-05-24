"""W9-MUTATION-CANARY: regression tests for the 3-mutant rolling spot-check.

Tests target the pure helpers (rotation, mutation application, report
formatting) and a tiny smoke test that runs the canary against a
self-contained fixture module so we don't pay for a 90s pytest
sub-run on every test sweep.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# Import the canary script as a module (it lives in scripts/, not src/).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_mutation_canary.py"
_spec = importlib.util.spec_from_file_location("run_mutation_canary", _SCRIPT)
canary = importlib.util.module_from_spec(_spec)
sys.modules["run_mutation_canary"] = canary
_spec.loader.exec_module(canary)


# -- Rotation state --------------------------------------------------------


def test_load_rotation_state_bootstraps_first_module(tmp_path, monkeypatch):
    state_path = tmp_path / "canary_state.json"
    monkeypatch.setattr(canary, "STATE_PATH", state_path)
    assert canary.load_rotation_state() == canary.ROTATION[0]


def test_load_rotation_state_reads_existing(tmp_path, monkeypatch):
    state_path = tmp_path / "canary_state.json"
    target = canary.ROTATION[2]
    state_path.write_text(json.dumps({"next_module": target}),
                          encoding="utf-8")
    monkeypatch.setattr(canary, "STATE_PATH", state_path)
    assert canary.load_rotation_state() == target


def test_load_rotation_state_falls_back_on_invalid_json(tmp_path, monkeypatch):
    state_path = tmp_path / "canary_state.json"
    state_path.write_text("not json{", encoding="utf-8")
    monkeypatch.setattr(canary, "STATE_PATH", state_path)
    assert canary.load_rotation_state() == canary.ROTATION[0]


def test_load_rotation_state_falls_back_on_unknown_module(tmp_path, monkeypatch):
    """A module not in the current rotation (e.g. removed in a refactor)
    should reset to ROTATION[0] not crash."""
    state_path = tmp_path / "canary_state.json"
    state_path.write_text(json.dumps({"next_module": "src/harness/removed.py"}),
                          encoding="utf-8")
    monkeypatch.setattr(canary, "STATE_PATH", state_path)
    assert canary.load_rotation_state() == canary.ROTATION[0]


def test_advance_rotation_cycles():
    first = canary.ROTATION[0]
    second = canary.advance_rotation(first)
    last = canary.ROTATION[-1]
    assert second == canary.ROTATION[1]
    # Last should wrap to first
    assert canary.advance_rotation(last) == first


def test_advance_rotation_handles_unknown_module():
    """An unknown module advances to ROTATION[0]."""
    assert canary.advance_rotation("src/harness/unknown.py") == canary.ROTATION[0]


def test_save_rotation_state_writes_pointer(tmp_path, monkeypatch):
    state_path = tmp_path / "canary_state.json"
    monkeypatch.setattr(canary, "STATE_PATH", state_path)
    canary.save_rotation_state(canary.ROTATION[2])
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["next_module"] == canary.ROTATION[2]
    assert "updated_at" in data


# -- Mutation application + restore ---------------------------------------


def test_apply_mutation_replaces_pattern(tmp_path):
    src = tmp_path / "victim.py"
    src.write_text("def f(): return True\n", encoding="utf-8")
    applied, original = canary.apply_mutation(src, "return True", "return False")
    assert applied
    assert original == "def f(): return True\n"
    assert src.read_text(encoding="utf-8") == "def f(): return False\n"


def test_apply_mutation_skips_when_pattern_absent(tmp_path):
    src = tmp_path / "victim.py"
    src.write_text("def f(): return None\n", encoding="utf-8")
    applied, original = canary.apply_mutation(src, "return True", "return False")
    assert not applied
    assert original == "def f(): return None\n"
    assert src.read_text(encoding="utf-8") == "def f(): return None\n"  # unchanged


def test_apply_mutation_replaces_only_first_occurrence(tmp_path):
    """str.replace(..., count=1) — only the first match flips."""
    src = tmp_path / "victim.py"
    src.write_text("a = True\nb = True\n", encoding="utf-8")
    applied, _ = canary.apply_mutation(src, "True", "False")
    assert applied
    text = src.read_text(encoding="utf-8")
    assert text == "a = False\nb = True\n"


def test_restore_module_reverts(tmp_path):
    src = tmp_path / "victim.py"
    src.write_text("mutated\n", encoding="utf-8")
    canary.restore_module(src, "original\n")
    assert src.read_text(encoding="utf-8") == "original\n"


# -- CanaryRun aggregation ------------------------------------------------


def _mk_result(label: str, applied: bool, killed: bool) -> "canary.CanaryResult":
    return canary.CanaryResult(
        module="src/foo/bar.py", label=label, pattern="x",
        applied=applied, killed=killed,
        failed_tests=1 if killed else 0,
        duration_s=1.0,
    )


def test_canary_run_all_killed_passes():
    run = canary.CanaryRun(module="src/foo/bar.py", started_at="2026-05-24T00:00:00Z")
    run.results = [_mk_result("m1", True, True), _mk_result("m2", True, True)]
    assert run.applied_count == 2
    assert run.killed_count == 2
    assert run.all_killed


def test_canary_run_with_survivor_fails():
    run = canary.CanaryRun(module="src/foo/bar.py", started_at="2026-05-24T00:00:00Z")
    run.results = [_mk_result("m1", True, True), _mk_result("m2", True, False)]
    assert run.applied_count == 2
    assert run.killed_count == 1
    assert not run.all_killed


def test_canary_run_zero_applied_is_neutral_pass():
    """If no mutations applied (all patterns absent), canary is neutral.

    The report should flag "no mutations applied" but the run should
    not fail — there's nothing to fail on.
    """
    run = canary.CanaryRun(module="src/foo/bar.py", started_at="2026-05-24T00:00:00Z")
    run.results = [_mk_result("m1", False, False), _mk_result("m2", False, False)]
    assert run.applied_count == 0
    assert run.all_killed  # neutral pass


# -- Report formatting ----------------------------------------------------


def test_format_report_lists_per_mutation_rows():
    run = canary.CanaryRun(module="src/foo/bar.py", started_at="2026-05-24T00:00:00Z")
    run.results = [
        _mk_result("bool_flip", True, True),
        _mk_result("eq_to_neq", True, False),  # survivor
        _mk_result("plus_minus", False, False),
    ]
    run.next_module = "src/foo/baz.py"
    body = canary.format_report(run)
    # Header
    assert "src/foo/bar.py" in body
    assert "Mutations applied: 2/3" in body
    assert "Mutations killed: 1/2" in body
    assert "canary FAIL" in body
    # Per-mutation table rows
    assert "`bool_flip`" in body
    assert "`eq_to_neq`" in body
    assert "`plus_minus`" in body
    # Survivor section
    assert "SURVIVING MUTATIONS" in body
    assert "`eq_to_neq` survived" in body
    assert "src/foo/baz.py" in body  # next module


def test_format_report_no_survivor_section_when_all_killed():
    run = canary.CanaryRun(module="src/foo/bar.py", started_at="2026-05-24T00:00:00Z")
    run.results = [_mk_result("m1", True, True)]
    body = canary.format_report(run)
    assert "canary PASS" in body
    assert "SURVIVING MUTATIONS" not in body


# -- End-to-end smoke: real module + real pytest (small) ------------------


def test_canary_run_against_fixture_module(tmp_path, monkeypatch):
    """Wire up the full run against a fixture module + tiny pytest run.

    The fixture module is *outside* the harness source tree.  We
    monkey-patch REPO_ROOT to the tmp_path so pytest cwd's there.

    This is a smoke test, not a perf test — we just verify the
    apply→pytest→restore→report path works end-to-end.

    NOTE: we skip the actual pytest sub-run (too slow for unit tests);
    instead we monkey-patch _run_pytest_x to return canned values.
    """
    # Fixture module under tmp_path that the canary will mutate
    fixture_dir = tmp_path / "src" / "fixmod"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "foo.py"
    fixture.write_text("def status(): return True\n", encoding="utf-8")

    monkeypatch.setattr(canary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(canary, "REPORT_DIR", tmp_path / "reports")

    # Stub the pytest sub-run: pretend it kills every mutation
    monkeypatch.setattr(canary, "_run_pytest_x",
                        lambda: (10, 1, 0.5))  # passed=10, failed=1, dur=0.5

    run = canary.run_canary("src/fixmod/foo.py", mutation_count=1)
    assert run.applied_count == 1
    assert run.killed_count == 1
    assert run.all_killed
    # Module restored
    assert fixture.read_text(encoding="utf-8") == "def status(): return True\n"


def test_canary_run_with_missing_module(monkeypatch, tmp_path):
    """A missing module produces failed-to-apply placeholders, not a crash."""
    monkeypatch.setattr(canary, "REPO_ROOT", tmp_path)
    run = canary.run_canary("src/missing/file.py", mutation_count=2)
    assert run.applied_count == 0
    assert len(run.results) == 2
    assert all(r.skipped_reason == "module file not found" for r in run.results)


def test_canary_run_restores_module_on_pytest_exception(tmp_path, monkeypatch):
    """If the pytest sub-run raises mid-flight, the module MUST be restored.

    This is the critical safety property — a crashed canary must
    never leave the source tree in a mutated state.
    """
    fixture_dir = tmp_path / "src" / "fixmod"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "foo.py"
    original_text = "def status(): return True\n"
    fixture.write_text(original_text, encoding="utf-8")

    monkeypatch.setattr(canary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(canary, "REPORT_DIR", tmp_path / "reports")

    def _boom():
        raise RuntimeError("simulated pytest crash")

    monkeypatch.setattr(canary, "_run_pytest_x", _boom)

    with pytest.raises(RuntimeError, match="simulated pytest crash"):
        canary.run_canary("src/fixmod/foo.py", mutation_count=1)

    # Critical: file is restored despite the crash
    assert fixture.read_text(encoding="utf-8") == original_text
