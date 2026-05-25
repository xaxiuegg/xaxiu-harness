"""W13-AUDIT-INFRA-W13-PLUS: regression tests for the 20-agent panel.

Locks in the STATUS.csv fallback path for W12+ task ids that have no
spec/wave-N-plan.md file.  Before this fix, every W13 row returned
``ERROR: task W13-FOO not found in plan spec\\wave-6-plan.md``.

Engine dispatch is monkeypatched away so these tests are pure-Python
fast — no real Kimi/MiMo traffic.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str):
    """Import a scripts/ module by file path."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def panel20():
    return _load("audit_w_action_panel20")


@pytest.fixture(scope="module")
def audit():
    return _load("audit_task_with_mimo")


def _seed_status_csv(tmp_path: Path, task_id: str, notes: str) -> Path:
    """Write a STATUS.csv with one matching row."""
    csv_path = tmp_path / "STATUS.csv"
    fieldnames = ["ID", "Category", "Title", "Status",
                  "Owner", "Effort", "Updated", "Notes"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "ID": task_id, "Category": "Production",
            "Title": "Test task", "Status": "shipped",
            "Owner": "Claude", "Effort": "~10min",
            "Updated": "2026-05-25", "Notes": notes,
        })
    return csv_path


def _stub_persona(panel20):
    """Return a fake _dispatch_persona that always returns a PASS verdict."""
    PersonaVerdict = panel20.PersonaVerdict

    def fake(engine_name, model, persona_id, persona_lens, base_prompt):
        return PersonaVerdict(
            persona_id=persona_id, engine=engine_name,
            success=True, confidence=0.85, verdict="PASS",
            lens_finding="mocked", criteria_gap="none",
            blocking_concern="none", latency_ms=1, raw_text="{}",
        )
    return fake


def _stub_git_info(shas):
    """Return a fake git_commits_info result; never shells out."""
    return {
        "sha": (shas[0] if shas else "HEAD") + "000000",
        "author": "tester", "date": "2026-05-25",
        "message": "test commit", "diffstat": "1 file",
        "diff_excerpt": "diff body", "file_contents": "(none)",
    }


def test_panel20_w13_routes_to_status_csv_and_runs_end_to_end(
    audit, panel20, tmp_path, monkeypatch,
):
    """W13-FOO via STATUS.csv must run the 20-persona panel, not ERROR.

    Pre-fix behavior: panel returned `panel_verdict == "ERROR"` with
    `error: task W13-FOO not found in plan spec\\wave-6-plan.md`
    because _resolve_plan_path fell through to the W6 plan.
    """
    csv_path = _seed_status_csv(
        tmp_path, "W13-FOO",
        "Acceptance: feature shipped, tests added, suite green.",
    )
    monkeypatch.setattr(audit, "STATUS_CSV_PATH", csv_path)
    monkeypatch.setattr(panel20, "_dispatch_persona", _stub_persona(panel20))
    monkeypatch.setattr(panel20, "git_commits_info", _stub_git_info)

    panel = panel20.run_panel("W13-FOO", "abc1234")

    assert panel["panel_verdict"] != "ERROR", panel.get("error")
    assert panel["panel_verdict"] == "PASS"
    assert panel["total_personas"] == 20
    assert panel["successful_personas"] == 20
    assert panel["mean_confidence"] >= 0.7


def test_panel20_w12_also_routes_to_status_csv(
    audit, panel20, tmp_path, monkeypatch,
):
    """W12-FOO has no spec/wave-12-plan.md either — same fallback."""
    csv_path = _seed_status_csv(tmp_path, "W12-FOO", "shipped notes")
    monkeypatch.setattr(audit, "STATUS_CSV_PATH", csv_path)
    monkeypatch.setattr(panel20, "_dispatch_persona", _stub_persona(panel20))
    monkeypatch.setattr(panel20, "git_commits_info", _stub_git_info)

    panel = panel20.run_panel("W12-FOO", "abc1234")
    assert panel["panel_verdict"] != "ERROR"
    assert panel["total_personas"] == 20


def test_panel20_w13_missing_status_row_returns_error(
    audit, panel20, tmp_path, monkeypatch,
):
    """If STATUS.csv exists but the row is missing, panel returns ERROR
    (not a crash) with a helpful message naming the STATUS.csv path.
    """
    csv_path = _seed_status_csv(tmp_path, "W13-OTHER", "other notes")
    monkeypatch.setattr(audit, "STATUS_CSV_PATH", csv_path)
    monkeypatch.setattr(panel20, "_dispatch_persona", _stub_persona(panel20))
    monkeypatch.setattr(panel20, "git_commits_info", _stub_git_info)

    panel = panel20.run_panel("W13-MISSING", "abc1234")
    assert panel["panel_verdict"] == "ERROR"
    assert "W13-MISSING" in panel.get("error", "")
    assert "STATUS.csv" in panel.get("error", "")


def test_panel20_real_w13_row_resolves_against_repo_status_csv(
    audit, panel20, monkeypatch,
):
    """Sanity check against the actual coord/STATUS.csv in the repo: a
    real W13 row that shipped this week must resolve to non-ERROR.

    The 8 already-shipped W13 rows (per W13-AUDIT-INFRA-W13-PLUS task
    description) should all load.  Pick W13-MORNING-BRIEF-CONTEXT-BUG
    as the canonical case.
    """
    monkeypatch.setattr(panel20, "_dispatch_persona", _stub_persona(panel20))
    monkeypatch.setattr(panel20, "git_commits_info", _stub_git_info)

    panel = panel20.run_panel(
        "W13-MORNING-BRIEF-CONTEXT-BUG", "d506b29",
    )
    assert panel["panel_verdict"] != "ERROR", panel.get("error")
    assert panel["total_personas"] == 20
