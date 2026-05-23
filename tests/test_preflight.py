"""Tests for harness.preflight — autonomous-mode readiness gate."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness import preflight
from harness.preflight import (
    PreflightCheck,
    _check_status_csv_fresh,
    _check_pytest_cache_green,
    _check_git_clean,
    overall_exit_code,
)


# ---------------------------------------------------------------------------
# Severity → exit code aggregation
# ---------------------------------------------------------------------------


def test_overall_exit_code_all_ok_returns_zero() -> None:
    results = [
        PreflightCheck(name="a", severity="ok", message="x"),
        PreflightCheck(name="b", severity="ok", message="y"),
    ]
    assert overall_exit_code(results) == 0


def test_overall_exit_code_any_warn_returns_one() -> None:
    results = [
        PreflightCheck(name="a", severity="ok", message="x"),
        PreflightCheck(name="b", severity="warn", message="y"),
    ]
    assert overall_exit_code(results) == 1


def test_overall_exit_code_any_fail_returns_four() -> None:
    results = [
        PreflightCheck(name="a", severity="ok", message="x"),
        PreflightCheck(name="b", severity="warn", message="y"),
        PreflightCheck(name="c", severity="fail", message="z"),
    ]
    assert overall_exit_code(results) == 4


def test_overall_exit_code_empty_returns_zero() -> None:
    assert overall_exit_code([]) == 0


# ---------------------------------------------------------------------------
# STATUS.csv freshness
# ---------------------------------------------------------------------------


def test_check_status_csv_missing(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "missing.csv"
    monkeypatch.setattr(preflight, "STATUS_CSV", fake)
    result = _check_status_csv_fresh()
    assert result.severity == "fail"
    assert "missing" in result.message


def test_check_status_csv_fresh_ok(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "status.csv"
    fake.write_text("ID,Title\n", encoding="utf-8")
    monkeypatch.setattr(preflight, "STATUS_CSV", fake)
    result = _check_status_csv_fresh()
    assert result.severity == "ok"
    assert "writable" in result.message


def test_check_status_csv_stale_warn(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "status.csv"
    fake.write_text("ID\n", encoding="utf-8")
    # Set mtime to 48h ago
    old = time.time() - (48 * 3600)
    os.utime(fake, (old, old))
    monkeypatch.setattr(preflight, "STATUS_CSV", fake)
    result = _check_status_csv_fresh(max_age_hours=24)
    assert result.severity == "warn"
    assert "stale" in result.message


# ---------------------------------------------------------------------------
# Pytest cache state
# ---------------------------------------------------------------------------


def test_check_pytest_cache_missing_warns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight, "PYTEST_CACHE", tmp_path / "nonexistent")
    result = _check_pytest_cache_green()
    assert result.severity == "warn"
    assert "no pytest cache" in result.message


def test_check_pytest_cache_empty_dict_is_ok(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "lastfailed"
    fake.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(preflight, "PYTEST_CACHE", fake)
    result = _check_pytest_cache_green()
    assert result.severity == "ok"


def test_check_pytest_cache_has_failures_is_fail(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "lastfailed"
    fake.write_text('{"tests/test_foo.py::test_bar": true}',
                    encoding="utf-8")
    monkeypatch.setattr(preflight, "PYTEST_CACHE", fake)
    result = _check_pytest_cache_green()
    assert result.severity == "fail"


# ---------------------------------------------------------------------------
# Git tree cleanliness — mocked subprocess
# ---------------------------------------------------------------------------


def test_check_git_clean_clean_tree_ok() -> None:
    with patch("harness.preflight.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = _check_git_clean()
    assert result.severity == "ok"
    assert "clean" in result.message


def test_check_git_clean_modified_tracked_is_fail() -> None:
    with patch("harness.preflight.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=" M src/foo.py\n M src/bar.py\n",
            returncode=0,
        )
        result = _check_git_clean()
    assert result.severity == "fail"
    assert "modified" in result.message


def test_check_git_clean_only_untracked_is_warn() -> None:
    with patch("harness.preflight.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="?? src/new.py\n?? tests/new.py\n",
            returncode=0,
        )
        result = _check_git_clean()
    assert result.severity == "warn"
    assert "untracked" in result.message


# ---------------------------------------------------------------------------
# Engine probe — mocked dispatch
# ---------------------------------------------------------------------------


def test_check_engine_probe_no_key_warns(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("no API key")
    monkeypatch.setattr("harness.engines.concrete.get_engine", _raise)
    result = preflight._check_engine_probe("deepseek")
    assert result.severity == "warn"
    assert "no API key" in result.message


def test_check_engine_probe_dispatch_success_with_tokens_ok(monkeypatch) -> None:
    fake_resp = MagicMock(
        success=True, tokens_in=10, tokens_out=5,
        latency_ms=1234, error=None,
    )
    fake_engine = MagicMock()
    fake_engine.dispatch.return_value = fake_resp
    monkeypatch.setattr(
        "harness.engines.concrete.get_engine", lambda *a, **k: fake_engine
    )
    result = preflight._check_engine_probe("deepseek")
    assert result.severity == "ok"
    assert "in=10/out=5" in result.message


def test_check_dead_engines_none_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "harness.engine_alarm.dead_engines", lambda: {}
    )
    result = preflight._check_dead_engines()
    assert result.severity == "ok"
    assert "below failure threshold" in result.message


def test_check_dead_engines_some_warns(monkeypatch) -> None:
    monkeypatch.setattr(
        "harness.engine_alarm.dead_engines",
        lambda: {"kimi": 7, "mimo": 5},
    )
    result = preflight._check_dead_engines()
    assert result.severity == "warn"
    assert "kimi:7" in result.message
    assert "mimo:5" in result.message


def test_check_engine_probe_zero_tokens_warns(monkeypatch) -> None:
    fake_resp = MagicMock(
        success=True, tokens_in=0, tokens_out=0,
        latency_ms=100, error=None,
    )
    fake_engine = MagicMock()
    fake_engine.dispatch.return_value = fake_resp
    monkeypatch.setattr(
        "harness.engines.concrete.get_engine", lambda *a, **k: fake_engine
    )
    result = preflight._check_engine_probe("deepseek")
    assert result.severity == "warn"
    assert "tokens_in=0" in result.message


# ---------------------------------------------------------------------------
# Run-all aggregation
# ---------------------------------------------------------------------------


def test_run_all_returns_sorted_results(monkeypatch) -> None:
    """Run_all returns checks sorted by name for deterministic CLI output."""
    # Stub every check callable to return a known PreflightCheck.
    def _stub(name: str):
        return lambda: PreflightCheck(
            name=name, severity="ok", message=f"stub:{name}",
        )

    pairs = [("zzz", _stub("zzz")), ("aaa", _stub("aaa")),
             ("mmm", _stub("mmm"))]
    monkeypatch.setattr(preflight, "_all_check_callables", lambda: pairs)
    results = preflight.run_all()
    names = [r.name for r in results]
    assert names == sorted(names)
    assert names == ["aaa", "mmm", "zzz"]


def test_run_all_isolates_check_failures(monkeypatch) -> None:
    """A check that raises is reported as a fail-severity result, not
    propagated to the caller."""
    def _good():
        return PreflightCheck(name="good", severity="ok", message="x")

    def _bad():
        raise RuntimeError("boom")

    pairs = [("good", _good), ("bad", _bad)]
    monkeypatch.setattr(preflight, "_all_check_callables", lambda: pairs)
    results = preflight.run_all()
    names_to_severity = {r.name: r.severity for r in results}
    assert names_to_severity["good"] == "ok"
    assert names_to_severity["bad"] == "fail"
    bad_result = next(r for r in results if r.name == "bad")
    assert "boom" in bad_result.message
