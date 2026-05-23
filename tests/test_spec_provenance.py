"""Tests for SPEC-PROVENANCE-TRAIL."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.coord.provenance import register, verify, _sha256_of


def _spec(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "spec.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_register_appends_entry(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    entry = register(spec, log_path=log)
    assert entry.sha256 == _sha256_of(spec)
    assert log.exists()
    rows = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["sha256"] == entry.sha256


def test_register_missing_spec_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        register(tmp_path / "nope.md", log_path=tmp_path / "prov.jsonl")


def test_verify_clean_passes(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    matches, msg = verify(spec, log_path=log)
    assert matches is True
    assert msg == "ok"


def test_verify_detects_tamper(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    spec.write_text("# tampered\n", encoding="utf-8")
    matches, msg = verify(spec, log_path=log)
    assert matches is False
    assert "tampered" in msg


def test_verify_no_registration(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "# spec\n")
    log = tmp_path / "prov.jsonl"
    matches, msg = verify(spec, log_path=log)
    assert matches is False


def test_verify_uses_latest_registration(tmp_path: Path) -> None:
    """If a spec is re-registered after edit, verify against the LATEST SHA."""
    spec = _spec(tmp_path, "# v1\n")
    log = tmp_path / "prov.jsonl"
    register(spec, log_path=log)
    spec.write_text("# v2\n", encoding="utf-8")
    register(spec, log_path=log)
    matches, msg = verify(spec, log_path=log)
    assert matches is True


def test_cli_spec_register(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# spec\n", encoding="utf-8")
        result = runner.invoke(cli, ["spec-register", str(spec)])
    assert result.exit_code == 0, result.output
    assert "registered:" in result.output
    assert "sha256:" in result.output


def test_cli_spec_verify_exits_1_on_mismatch(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        spec = iso_path / "spec.md"
        spec.write_text("# v1\n", encoding="utf-8")
        runner.invoke(cli, ["spec-register", str(spec)])
        spec.write_text("# tampered\n", encoding="utf-8")
        result = runner.invoke(cli, ["spec-verify", str(spec)])
    assert result.exit_code == 1
    assert "MISMATCH" in result.output


# ---------------------------------------------------------------------------
# W5-KK harness spec-init
# ---------------------------------------------------------------------------

def test_spec_init_creates_canonical_template(tmp_path: Path) -> None:
    """spec-init writes a markdown with all 4 canonical sections."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["spec-init", "my-feature", "--out", str(tmp_path),
              "--goal", "Test the thing"],
    )
    assert result.exit_code == 0, f"output={result.output}"
    spec = tmp_path / "my-feature.md"
    assert spec.exists()
    body = spec.read_text(encoding="utf-8")
    assert "# SPEC-ID: my-feature" in body
    assert "## Goal" in body
    assert "Test the thing" in body
    assert "## Strict Paths" in body
    assert "## Acceptance" in body
    assert "## Why this spec exists" in body


def test_spec_init_inlines_strict_paths(tmp_path: Path) -> None:
    """--strict-paths CSV becomes a bullet list under Strict Paths."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["spec-init", "demo", "--out", str(tmp_path),
              "--strict-paths", "coord/a.md,coord/b.md, coord/c.md "],
    )
    assert result.exit_code == 0
    spec = tmp_path / "demo.md"
    body = spec.read_text(encoding="utf-8")
    # Each path becomes a bullet entry (whitespace trimmed)
    assert "- coord/a.md" in body
    assert "- coord/b.md" in body
    assert "- coord/c.md" in body
    # No example comment block when explicit paths are provided
    assert "<!-- Example:" not in body


def test_spec_init_round_trips_through_planner_extractor(tmp_path: Path) -> None:
    """W5-BB integration: spec-init output is parseable by
    `_extract_strict_paths` so the round trip is consistent."""
    from harness.coord.planner import _extract_strict_paths
    runner = CliRunner()
    runner.invoke(
        cli, ["spec-init", "rt", "--out", str(tmp_path),
              "--strict-paths", "coord/x.md,coord/y.md"],
    )
    spec_text = (tmp_path / "rt.md").read_text(encoding="utf-8")
    assert _extract_strict_paths(spec_text) == ["coord/x.md", "coord/y.md"]


def test_spec_init_refuses_existing_file(tmp_path: Path) -> None:
    """Don't clobber an existing spec."""
    runner = CliRunner()
    runner.invoke(cli, ["spec-init", "x", "--out", str(tmp_path)])
    result = runner.invoke(cli, ["spec-init", "x", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_spec_init_slugifies_name(tmp_path: Path) -> None:
    """Names with spaces / odd chars get slugified into a valid filename."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["spec-init", "My Cool Feature!", "--out", str(tmp_path)],
    )
    assert result.exit_code == 0
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    # Slug is hyphenated, no spaces / punctuation
    assert " " not in files[0].name
    assert "!" not in files[0].name
