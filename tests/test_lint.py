"""Tests for SPEC-LINT (lint.py + lint-spec CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.lint import lint_spec, is_plan_ready, LintFinding


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "spec.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_lint_missing_file(tmp_path: Path) -> None:
    findings = lint_spec(tmp_path / "nope.md")
    assert any(f.code == "E_NOT_FOUND" for f in findings)


def test_lint_empty_spec(tmp_path: Path) -> None:
    findings = lint_spec(_write(tmp_path, "   \n   "))
    assert any(f.code == "E_EMPTY" for f in findings)


def test_lint_too_short_spec(tmp_path: Path) -> None:
    findings = lint_spec(_write(tmp_path, "# spec\nonly one line"))
    assert any(f.code == "E_TOO_SHORT" for f in findings)


def test_lint_unresolved_placeholder(tmp_path: Path) -> None:
    findings = lint_spec(_write(tmp_path,
        "# spec\n\nAdd a feature {{FEATURE_NAME}}\n\n## Acceptance\n- works"))
    assert any(f.code == "E_UNRESOLVED_PLACEHOLDER" for f in findings)


def test_lint_warn_no_acceptance(tmp_path: Path) -> None:
    findings = lint_spec(_write(tmp_path,
        "# spec\n\nLong-enough body that has\nmultiple lines but no\ncriteria defined\n"))
    assert any(f.code == "W_NO_ACCEPTANCE" for f in findings)
    # warn-only ⇒ still plan-ready
    assert is_plan_ready(findings) is True


def test_lint_clean_spec_has_no_findings(tmp_path: Path) -> None:
    findings = lint_spec(_write(tmp_path,
        "# spec\n\nAdd a /health endpoint to dashboard.\n\n"
        "## Acceptance\n- /health returns 200\n- response includes {status: ok}\n"))
    assert findings == [] or all(f.severity == "warn" for f in findings)
    assert is_plan_ready(findings) is True


def test_cli_lint_spec_clean(tmp_path: Path) -> None:
    runner = CliRunner()
    spec = _write(tmp_path,
        "# spec\n\nAdd /health route.\n\n## Acceptance\n- /health returns 200\n")
    result = runner.invoke(cli, ["lint-spec", str(spec)])
    assert result.exit_code == 0, result.output
    assert "plan_ready: True" in result.output


def test_cli_lint_spec_error_exits_1(tmp_path: Path) -> None:
    runner = CliRunner()
    spec = _write(tmp_path, "")
    result = runner.invoke(cli, ["lint-spec", str(spec)])
    assert result.exit_code == 1
    assert "E_EMPTY" in result.output


def test_cli_lint_spec_json_format(tmp_path: Path) -> None:
    import json
    runner = CliRunner()
    spec = _write(tmp_path,
        "# spec\n\nAdd a route.\n\n## Acceptance\n- works\n")
    result = runner.invoke(cli, ["lint-spec", str(spec), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["plan_ready"] is True
    assert "findings" in data
