"""Tests for PANIC-DUMP."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.panic import panic_dump, _scrub_text


def test_scrub_redacts_sk_keys() -> None:
    s = "key=sk-AAAAAAAAAAAAAAAAAAAAAAAAAA"
    out = _scrub_text(s)
    assert "sk-AAAAA" not in out
    assert "REDACTED" in out


def test_scrub_redacts_bearer_tokens() -> None:
    s = "Authorization: Bearer abcdefghijklmnopqrstuv"
    out = _scrub_text(s)
    assert "REDACTED" in out
    assert "abcdefghij" not in out


def test_scrub_redacts_env_KEY_values() -> None:
    s = "KIMI_API_KEY=secretvaluehere"
    out = _scrub_text(s)
    assert "secretvaluehere" not in out
    assert "KIMI_API_KEY" in out  # name kept, value redacted


def test_panic_dump_creates_tarball(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = panic_dump(target_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".gz"
    assert "panic-" in out.name


def test_panic_dump_skips_missing_files(tmp_path: Path, monkeypatch) -> None:
    """No coord/, no state/, no .harness/ — dump still produces a tarball."""
    monkeypatch.chdir(tmp_path)
    out = panic_dump(target_dir=tmp_path)
    assert out.exists()
    # Open + verify it's a valid gz tarball
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    # git.txt is always emitted (even if git fails)
    assert any("git.txt" in n for n in names) or names == []


def test_panic_dump_includes_status_csv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "STATUS.csv").write_text(
        "ID,Category,Title,Status\nA,Production,t,queued\n", encoding="utf-8")
    out = panic_dump(target_dir=tmp_path)
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert any("status.csv" in n for n in names)
        # Confirm content is in there
        member = next(t for t in tar.getmembers() if "status.csv" in t.name)
        content = tar.extractfile(member).read().decode("utf-8")
        assert "A,Production" in content


def test_cli_panic_dump(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["panic-dump", "--target-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "panic-dump written:" in result.output
