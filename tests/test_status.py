"""Tests for harness.status — canonical STATUS tracker (#19)."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from harness.status import (
    Status,
    StatusRow,
    add_row,
    read_status,
    summary,
    update_row,
    verify,
    write_status,
)
from harness.status import hooks
from harness.status.store import DEFAULT_STATUS_PATH


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestStatusEnum:
    def test_status_enum_has_all_required_values(self) -> None:
        expected = {
            "shipped", "in_progress", "queued", "todo", "blocked",
            "deferred", "partial", "proposed", "parked", "spec-done",
            "design-done", "planned",
            # W11 planning workflow lifecycle states (2026-05-25)
            "split", "merged",
        }
        actual = {s.value for s in Status}
        assert actual == expected

    def test_status_is_str_subclass(self) -> None:
        assert isinstance(Status.SHIPPED, str)
        assert Status.SHIPPED == "shipped"


class TestStatusRowSchema:
    def _minimal(self, **overrides):
        base = dict(
            id="TEST-001",
            category="Test",
            title="A test row",
            status=Status.TODO,
            owner="Claude",
        )
        base.update(overrides)
        return base

    def test_minimum_required_fields_validates(self) -> None:
        row = StatusRow(**self._minimal())
        assert row.id == "TEST-001"
        assert row.status == Status.TODO
        assert row.effort == "-"
        assert row.updated == "-"
        assert row.notes == ""

    def test_blank_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(id=""))

    def test_lowercase_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(id="test-001"))

    def test_id_must_start_with_alnum(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(id="-LEADING-DASH"))

    def test_id_allows_slash_and_underscore(self) -> None:
        row = StatusRow(**self._minimal(id="WAVE_5/A"))
        assert row.id == "WAVE_5/A"

    def test_oversized_title_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(title="x" * 201))

    def test_oversized_notes_rejected(self) -> None:
        # max_length raised 1000→4000 on 2026-05-22 to accommodate
        # verbose multi-engine defect logs from battle tests.
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(notes="x" * 4001))

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(status="not_a_status"))

    def test_malformed_updated_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(updated="2026/05/20"))

    def test_dash_updated_accepted(self) -> None:
        row = StatusRow(**self._minimal(updated="-"))
        assert row.updated == "-"

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StatusRow(**self._minimal(extra_field="boom"))


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_existing_status_csv_loads_cleanly(self) -> None:
        """The canonical coord/STATUS.csv must validate against the new schema."""
        repo_status = Path(__file__).parent.parent / "coord" / "STATUS.csv"
        rows = read_status(repo_status)
        assert len(rows) >= 30  # session has accumulated 38 by now
        for r in rows:
            assert isinstance(r, StatusRow)

    def test_roundtrip_preserves_all_rows(self, tmp_path: Path) -> None:
        repo_status = Path(__file__).parent.parent / "coord" / "STATUS.csv"
        rows = read_status(repo_status)
        out = tmp_path / "rt.csv"
        write_status(out, rows)
        rows2 = read_status(out)
        assert rows == rows2

    def test_empty_path_returns_empty_list(self, tmp_path: Path) -> None:
        missing = tmp_path / "no.csv"
        assert read_status(missing) == []

    def test_write_then_read_preserves_special_chars(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        rows = [
            StatusRow(
                id="X-1", category="Cat", title="Quotes \"and\" commas, here",
                status=Status.TODO, owner="Claude",
                notes="multi, comma, notes",
            ),
        ]
        write_status(p, rows)
        rows2 = read_status(p)
        assert rows2[0].notes == "multi, comma, notes"
        assert "Quotes" in rows2[0].title


class TestAddUpdate:
    def test_add_row_appends(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        add_row(p, StatusRow(id="A-1", category="C", title="t", status=Status.TODO, owner="C"))
        rows = read_status(p)
        assert len(rows) == 1 and rows[0].id == "A-1"

    def test_add_duplicate_id_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        row = StatusRow(id="A-1", category="C", title="t", status=Status.TODO, owner="C")
        add_row(p, row)
        with pytest.raises(ValueError, match="already exists"):
            add_row(p, row)

    def test_update_row_bumps_updated_to_today(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="A-1", category="C", title="t", status=Status.TODO,
                      owner="C", updated="-")
        ])
        updated = update_row(p, "A-1", status="shipped", notes="done")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert updated.updated == today
        assert updated.status == Status.SHIPPED
        assert updated.notes == "done"

    def test_update_unknown_raises_keyerror(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        with pytest.raises(KeyError, match="not found"):
            update_row(p, "NOPE")


class TestAtomicWrite:
    def test_failure_leaves_original_intact(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        good = [StatusRow(id="A-1", category="C", title="t", status=Status.TODO, owner="C")]
        write_status(p, good)
        original = p.read_text(encoding="utf-8")

        # Mock os.replace to raise; original must survive
        bad = [StatusRow(id="A-2", category="C", title="boom", status=Status.TODO, owner="C")]
        with patch("harness.status.store.os.replace", side_effect=OSError("nope")):
            with pytest.raises(OSError):
                write_status(p, bad)
        assert p.read_text(encoding="utf-8") == original
        # Tempfile cleanup verified separately

    def test_no_dangling_temp_after_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        with patch("harness.status.store.os.replace", side_effect=OSError):
            with pytest.raises(OSError):
                write_status(p, [
                    StatusRow(id="X", category="c", title="t", status=Status.TODO, owner="o")
                ])
        # Check no .status_* lingering
        leftovers = list(tmp_path.glob(".status_*"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# Summary + verify
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_counts_match_actual(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        rows = [
            StatusRow(id="A-1", category="C", title="t", status=Status.SHIPPED, owner="C"),
            StatusRow(id="A-2", category="C", title="t", status=Status.SHIPPED, owner="C"),
            StatusRow(id="A-3", category="C", title="t", status=Status.TODO, owner="C"),
        ]
        write_status(p, rows)
        out = summary(p)
        assert out[Status.SHIPPED] == 2
        assert out[Status.TODO] == 1
        assert out[Status.QUEUED] == 0


class TestVerify:
    def test_clean_file_no_issues(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="A-1", category="C", title="t", status=Status.SHIPPED, owner="C",
                      updated="2026-05-20"),
        ])
        assert verify(p, expected_cadence_minutes=60) == []

    def test_missing_file_returns_issue(self, tmp_path: Path) -> None:
        issues = verify(tmp_path / "missing.csv", expected_cadence_minutes=60)
        assert any("not exist" in i.lower() for i in issues)

    def test_stuck_in_progress_old_date(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="A-1", category="C", title="t", status=Status.IN_PROGRESS,
                      owner="C", updated="2020-01-01"),
        ])
        issues = verify(p, expected_cadence_minutes=60)
        assert any("in_progress" in i.lower() for i in issues)

    def test_stale_mtime_flagged(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="A-1", category="C", title="t", status=Status.IN_PROGRESS,
                      owner="C", updated=datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        ])
        # Backdate mtime by ~1 day
        ancient = datetime.now(timezone.utc).timestamp() - 86400
        os.utime(p, (ancient, ancient))
        issues = verify(p, expected_cadence_minutes=60)
        assert any("stale" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Hooks tests
# ---------------------------------------------------------------------------


class TestHooks:
    def test_on_dispatch_start_creates_row(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        hooks.on_dispatch_start(
            task_id="bg-1", wave_id="WAVE-1", engine="swarm/kimi",
            title="Test wave", category="Wave 1", owner="Kimi",
            path=p,
        )
        rows = read_status(p)
        assert len(rows) == 1
        assert rows[0].id == "WAVE-1"
        assert rows[0].status == Status.IN_PROGRESS
        assert "task=bg-1" in rows[0].notes
        assert "engine=swarm/kimi" in rows[0].notes

    def test_on_dispatch_start_transitions_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="WAVE-1", category="Wave", title="Existing",
                      status=Status.QUEUED, owner="Claude"),
        ])
        hooks.on_dispatch_start(
            task_id="bg-1", wave_id="WAVE-1", engine="swarm/kimi", path=p,
        )
        rows = read_status(p)
        assert len(rows) == 1
        assert rows[0].status == Status.IN_PROGRESS

    def test_on_dispatch_complete_success_maps_to_shipped(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        hooks.on_dispatch_start(task_id="bg-1", wave_id="W-1", engine="kimi", path=p)
        hooks.on_dispatch_complete(
            task_id="bg-1", wave_id="W-1", outcome="success",
            commit_sha="abcd1234567890ff", path=p,
        )
        rows = read_status(p)
        assert rows[0].status == Status.SHIPPED
        assert "commit=abcd12345678" in rows[0].notes

    def test_on_dispatch_complete_partial_maps_to_partial(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        hooks.on_dispatch_start(task_id="bg-1", wave_id="W-1", engine="kimi", path=p)
        hooks.on_dispatch_complete(
            task_id="bg-1", wave_id="W-1", outcome="timeout", path=p,
        )
        rows = read_status(p)
        assert rows[0].status == Status.PARTIAL

    def test_on_dispatch_complete_unknown_wave_noops(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [])
        hooks.on_dispatch_complete(
            task_id="bg-1", wave_id="NEVER-STARTED", outcome="success", path=p,
        )
        # No exception, no row added
        assert read_status(p) == []

    def test_on_commit_marks_shipped(self, tmp_path: Path) -> None:
        p = tmp_path / "s.csv"
        write_status(p, [
            StatusRow(id="W-1", category="W", title="t", status=Status.IN_PROGRESS,
                      owner="C"),
        ])
        hooks.on_commit(wave_id="W-1", commit_sha="abc1234567ab", files=["a", "b"], path=p)
        rows = read_status(p)
        assert rows[0].status == Status.SHIPPED
        assert "commit=abc1234567ab" in rows[0].notes
        assert "files=2" in rows[0].notes


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the CLI inside ``tmp_path`` with a coord/ subdir."""
    coord = tmp_path / "coord"
    coord.mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestStatusCLI:
    def _import_cli(self):
        from harness.cli import cli
        return cli

    def test_status_init_creates_file(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        result = CliRunner().invoke(cli, ["status", "init"])
        assert result.exit_code == 0, result.output
        assert (isolated_cwd / "coord" / "STATUS.csv").exists()

    def test_status_init_refuses_existing(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        result = runner.invoke(cli, ["status", "init"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower() or "exists" in result.output.lower()

    def test_status_init_force_overwrites(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        # Add a row, then init --force should wipe
        runner.invoke(cli, ["status", "add", "X-1", "Cat", "Title"])
        result = runner.invoke(cli, ["status", "init", "--force"])
        assert result.exit_code == 0
        rows = read_status(isolated_cwd / "coord" / "STATUS.csv")
        assert rows == []

    def test_status_add_appends_row(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        result = runner.invoke(cli, ["status", "add", "ADD-1", "Test", "Hello", "--status", "todo"])
        assert result.exit_code == 0, result.output
        rows = read_status(isolated_cwd / "coord" / "STATUS.csv")
        assert len(rows) == 1 and rows[0].id == "ADD-1"

    def test_status_update_modifies(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        runner.invoke(cli, ["status", "add", "UPD-1", "C", "Title"])
        result = runner.invoke(cli, [
            "status", "update", "UPD-1", "--status", "shipped", "--notes", "done",
        ])
        assert result.exit_code == 0, result.output
        rows = read_status(isolated_cwd / "coord" / "STATUS.csv")
        assert rows[0].status == Status.SHIPPED
        assert rows[0].notes == "done"

    def test_status_list_pretty(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        runner.invoke(cli, ["status", "add", "LIST-1", "C", "First"])
        result = runner.invoke(cli, ["status", "list"])
        assert result.exit_code == 0
        assert "LIST-1" in result.output

    def test_status_summary(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        runner.invoke(cli, ["status", "add", "S-1", "C", "T", "--status", "shipped"])
        runner.invoke(cli, ["status", "add", "S-2", "C", "T", "--status", "todo"])
        result = runner.invoke(cli, ["status", "summary"])
        assert result.exit_code == 0
        assert "shipped" in result.output

    def test_status_verify_clean(self, isolated_cwd: Path) -> None:
        cli = self._import_cli()
        runner = CliRunner()
        runner.invoke(cli, ["status", "init"])
        runner.invoke(cli, ["status", "add", "V-1", "C", "T", "--status", "shipped"])
        result = runner.invoke(cli, ["status", "verify"])
        assert result.exit_code == 0
