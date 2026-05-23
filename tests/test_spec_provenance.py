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


# ---------------------------------------------------------------------------
# W5-QQ SPECLIB — --from-template / --list-templates
# ---------------------------------------------------------------------------

def test_spec_init_list_templates_shows_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-QQ: --list-templates lists *.md files in spec/samples/."""
    samples = tmp_path / "spec" / "samples"
    samples.mkdir(parents=True)
    (samples / "demo-a.md").write_text(
        "# SPEC-ID: demo-a — First Demo\n\nbody\n", encoding="utf-8",
    )
    (samples / "demo-b.md").write_text(
        "# SPEC-ID: demo-b — Second Demo\n\nbody\n", encoding="utf-8",
    )
    # Pin _samples_dir to the test fixture so the harness's real samples
    # dir doesn't take precedence.
    monkeypatch.setattr("harness.cli._samples_dir", lambda: samples)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["spec-init", "--list-templates"])
    assert result.exit_code == 0, f"output={result.output}"
    assert "demo-a" in result.output
    assert "First Demo" in result.output
    assert "demo-b" in result.output


def test_spec_init_list_templates_handles_missing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-QQ: --list-templates with no spec/samples/ exits cleanly with
    an informative message (no crash)."""
    # Patch _samples_dir to point at an empty tmp path so neither cwd
    # nor the package's own samples dir resolve.
    empty = tmp_path / "no-such-dir"
    monkeypatch.setattr("harness.cli._samples_dir", lambda: empty)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["spec-init", "--list-templates"])
    assert result.exit_code == 0
    # Output should at least mention "no template" or the missing path
    assert "no template" in result.output.lower()


def test_spec_init_from_template_copies_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-QQ: --from-template TPL copies spec/samples/TPL.md content,
    replacing the SPEC-ID header with the new slug."""
    samples = tmp_path / "spec" / "samples"
    samples.mkdir(parents=True)
    template = samples / "my-tpl.md"
    template.write_text(
        "# SPEC-ID: my-tpl — Template Title\n\n"
        "## Goal\nDo something cool.\n\n"
        "## Strict Paths\n- coord/x.md\n\n"
        "## Acceptance\n1. X exists.\n\n"
        "## Why this spec exists\nReason.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("harness.cli._samples_dir", lambda: samples)
    out_dir = tmp_path / "out"
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["spec-init", "my-instance",
              "--from-template", "my-tpl",
              "--out", str(out_dir)],
    )
    assert result.exit_code == 0, f"output={result.output}"
    spec = out_dir / "my-instance.md"
    assert spec.exists()
    body = spec.read_text(encoding="utf-8")
    # New SPEC-ID, original body preserved
    assert body.splitlines()[0] == (
        "# SPEC-ID: my-instance — copied from my-tpl.md"
    )
    assert "Do something cool." in body
    assert "- coord/x.md" in body


def test_spec_init_from_template_errors_when_template_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-QQ: --from-template with a name that doesn't exist exits with
    an error message pointing to --list-templates."""
    samples = tmp_path / "spec" / "samples"
    samples.mkdir(parents=True)
    monkeypatch.setattr("harness.cli._samples_dir", lambda: samples)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["spec-init", "x",
              "--from-template", "doesnt-exist",
              "--out", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "not found" in result.output
    assert "list-templates" in result.output


def test_spec_init_requires_name_when_not_listing(tmp_path: Path) -> None:
    """W5-QQ: NAME is optional only when --list-templates is given."""
    runner = CliRunner()
    result = runner.invoke(cli, ["spec-init", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "NAME is required" in result.output


# ---------------------------------------------------------------------------
# W5-RR morning-brief
# ---------------------------------------------------------------------------

def test_morning_brief_help_lists_options() -> None:
    """W5-RR: CLI surface includes since-hours, out, engine, model, dry-run."""
    runner = CliRunner()
    result = runner.invoke(cli, ["morning-brief", "--help"])
    assert result.exit_code == 0
    assert "--since-hours" in result.output
    assert "--out" in result.output
    assert "--engine" in result.output
    assert "--model" in result.output
    assert "--dry-run" in result.output


def test_morning_brief_dry_run_emits_context_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-RR: --dry-run prints the context packet that WOULD be dispatched,
    no engine call, exit 0."""
    monkeypatch.chdir(tmp_path)
    # Seed minimal STATUS.csv so the context isn't empty
    (tmp_path / "coord").mkdir()
    status_csv = tmp_path / "coord" / "STATUS.csv"
    today = "2026-05-23"
    status_csv.write_text(
        f"ID,Category,Title,Status,Owner,Effort,Updated,Notes\n"
        f"W5-TEST,Production,Test row,shipped,Claude,~10 min,{today},Test notes\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["morning-brief", "--dry-run"])
    assert result.exit_code == 0, f"output={result.output}"
    assert "DRY RUN" in result.output
    assert "W5-TEST" in result.output
    assert "morning brief" in result.output.lower()


def test_morning_brief_exits_2_when_no_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-RR: empty cwd → exit 2 with a clear error message."""
    # Patch list_pending_flags so it doesn't accidentally pick up the
    # harness repo's own observer state outside the test's tmp_path.
    monkeypatch.setattr(
        "harness.observer.flags.list_pending_flags", lambda: {},
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["morning-brief", "--dry-run"])
    assert result.exit_code == 2, f"output={result.output}"
    assert "no context found" in result.output.lower()
