"""Tests for `harness today` — W8-STATUS-HUMAN."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli


def _write_status_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ID", "Category", "Title", "Status", "Owner", "Effort",
              "Updated", "Notes"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )


def _old_date_str() -> str:
    """A date well outside the 24h window."""
    return (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
        "%Y-%m-%d"
    )


def test_today_no_status_csv_doesnt_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator runs `harness today` in a fresh clone — no STATUS.csv
    yet.  Should not crash; should say nothing-shipped + suggest
    actions."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "--since-hours", "24"])
    assert result.exit_code == 0
    assert "nothing shipped" in result.output.lower()


def test_today_shows_recent_shipped_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STATUS.csv has 2 recent-shipped + 1 stale-shipped + 1 queued.
    Output lists the 2 recent shipped, hides the stale + queued."""
    monkeypatch.chdir(tmp_path)
    _write_status_csv(tmp_path / "coord" / "STATUS.csv", [
        {"ID": "W8-RECENT", "Title": "Recent ship",
         "Status": "shipped", "Updated": _today_str()},
        {"ID": "W7-RECENT", "Title": "Yesterday ship",
         "Status": "shipped", "Updated": _yesterday_str()},
        {"ID": "W1-STALE", "Title": "Old ship",
         "Status": "shipped", "Updated": _old_date_str()},
        {"ID": "W9-QUEUED", "Title": "Queued",
         "Status": "queued", "Updated": _today_str()},
    ])
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "--since-hours", "48"])
    assert result.exit_code == 0
    assert "Recent ship" in result.output
    assert "Yesterday ship" in result.output
    # Stale and queued must not appear
    assert "Old ship" not in result.output
    assert "Queued" not in result.output


def test_today_audit_counts_correct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drop 2 PASS + 1 STOP audit reports into the directory; the
    output should show '2 PASS, 1 STOP'."""
    monkeypatch.chdir(tmp_path)
    audit_dir = tmp_path / "coord" / "reviews" / "audits"
    audit_dir.mkdir(parents=True)
    (audit_dir / "20260524_pass1_audit.md").write_text(
        "<!-- engine=mimo task=W8-PASS-A confidence=0.85 -->\n",
        encoding="utf-8",
    )
    (audit_dir / "20260524_pass2_audit.md").write_text(
        "<!-- engine=mimo task=W8-PASS-B confidence=0.72 -->\n",
        encoding="utf-8",
    )
    (audit_dir / "20260524_stop1_audit.md").write_text(
        "<!-- engine=mimo task=W8-STOP confidence=0.40 -->\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "--since-hours", "24"])
    assert result.exit_code == 0
    assert "2 PASS" in result.output
    assert "1 STOP" in result.output
    # Each audit task ID should appear (truncated to 6 in pretty mode)
    assert "W8-PASS-A" in result.output
    assert "W8-STOP" in result.output


def test_today_blockers_include_preflight_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When preflight returns a fail-severity check, `today` lists it
    as a blocker AND suggests `preflight --fix --dry-run`."""
    monkeypatch.chdir(tmp_path)
    # Stub preflight to return a known failure
    from harness.preflight import PreflightCheck
    monkeypatch.setattr(
        "harness.preflight.run_all", lambda: [
            PreflightCheck(name="git_clean", severity="fail",
                           message="6 modified files",
                           fix="commit or stash"),
        ],
    )
    # Avoid real engine probes
    monkeypatch.setattr(
        "harness.preflight._all_check_callables",
        lambda: [("git_clean", lambda: PreflightCheck(
            name="git_clean", severity="fail",
            message="6 modified files"))]
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["today", "--since-hours", "24"])
    assert result.exit_code == 0
    assert "[X] git_clean" in result.output
    assert "preflight --fix" in result.output


def test_today_green_state_suggests_morning_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When everything's green, the suggestion is morning-brief +
    do non-harness work."""
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck
    monkeypatch.setattr(
        "harness.preflight._all_check_callables",
        lambda: [("git_clean", lambda: PreflightCheck(
            name="git_clean", severity="ok", message="clean"))]
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["today"])
    assert result.exit_code == 0
    assert "None — preflight is green" in result.output
    # Green path suggestion: morning-brief
    assert "morning-brief" in result.output


def test_today_links_to_operator_runbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Footer always links to the runbook so the operator knows where
    to look next."""
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck
    monkeypatch.setattr(
        "harness.preflight._all_check_callables",
        lambda: [("git_clean", lambda: PreflightCheck(
            name="git_clean", severity="ok", message="clean"))]
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["today"])
    assert result.exit_code == 0
    assert "OPERATOR_RUNBOOK.md" in result.output


def test_today_no_traceback_on_audit_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No audit dir → 'no audits ran' message, not a crash."""
    monkeypatch.chdir(tmp_path)
    from harness.preflight import PreflightCheck
    monkeypatch.setattr(
        "harness.preflight._all_check_callables",
        lambda: [("git_clean", lambda: PreflightCheck(
            name="git_clean", severity="ok", message="clean"))]
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["today"])
    assert result.exit_code == 0
    assert "no audits ran" in result.output.lower()
