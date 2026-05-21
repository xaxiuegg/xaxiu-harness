# SPEC-LINT — `harness lint-spec <spec.md>` plan-readiness validator

## Goal

Cheap pre-flight check that a markdown spec is likely to plan cleanly
before any engine spend.  Catches: empty spec, missing acceptance section,
unresolved `{{placeholder}}` tokens, vague single-verb instructions.

CLI verb is TOP-LEVEL (`harness lint-spec`), NOT `harness coord lint`,
to avoid touching the coord_group block in cli.py.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/lint.py`

```python
"""Spec-readiness linter (SPEC-LINT, 2026-05-21).

Heuristic checks that fire BEFORE any planner dispatch — cheap, offline,
deterministic.  Each finding has a severity ("error" or "warn") and a
short message.  Errors block a dispatch; warns are informational only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LintFinding:
    severity: str  # "error" | "warn"
    code: str
    message: str


# A short whitelist of "vague" lone verbs that almost always need
# operator clarification before a worker can act on them.
_VAGUE_VERBS = frozenset({"improve", "refactor", "clean up", "fix bug", "optimize"})


def lint_spec(spec_path: Path) -> list[LintFinding]:
    """Return a list of findings; empty list = spec is plan-ready."""
    findings: list[LintFinding] = []
    if not spec_path.exists():
        findings.append(LintFinding("error", "E_NOT_FOUND",
                                    f"spec file does not exist: {spec_path}"))
        return findings
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        findings.append(LintFinding("error", "E_READ_FAILED", str(exc)))
        return findings

    body = text.strip()
    if not body:
        findings.append(LintFinding("error", "E_EMPTY", "spec is empty"))
        return findings

    lines = body.splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    if len(non_blank) < 3:
        findings.append(LintFinding("error", "E_TOO_SHORT",
                                    f"spec has only {len(non_blank)} non-blank lines (need ≥3)"))

    # Acceptance criteria — a key planner anchor
    text_lc = body.lower()
    if "acceptance" not in text_lc and "outcome" not in text_lc and "done when" not in text_lc:
        findings.append(LintFinding("warn", "W_NO_ACCEPTANCE",
                                    "spec has no 'acceptance' / 'outcome' / 'done when' section"))

    # Unresolved placeholders
    placeholders = re.findall(r"\{\{[^}]+\}\}", body)
    for ph in set(placeholders):
        findings.append(LintFinding("error", "E_UNRESOLVED_PLACEHOLDER",
                                    f"unresolved placeholder {ph!r}"))

    # Vague-verb detection (only as a warn — humans need wiggle room)
    bullet_starts = [ln.strip().lstrip("-*0123456789. )").strip().lower()
                     for ln in lines if ln.strip().startswith(("-", "*"))]
    for bullet in bullet_starts:
        first_words = " ".join(bullet.split()[:2])
        if first_words in _VAGUE_VERBS or bullet.split()[:1] and bullet.split()[0] in _VAGUE_VERBS:
            findings.append(LintFinding("warn", "W_VAGUE_VERB",
                                        f"bullet starts with vague verb: {bullet[:60]!r}"))
            break  # one warning per spec is enough

    return findings


def is_plan_ready(findings: list[LintFinding]) -> bool:
    """Return True if no findings have severity 'error'."""
    return not any(f.severity == "error" for f in findings)
```

### 2. New TOP-LEVEL CLI command

In `src/harness/cli.py`, find an existing top-level command (search for
`@cli.command(name="dashboard-serve")`) and add a NEW top-level command
RIGHT BEFORE OR AFTER it (so it ends up grouped with other top-level
commands, NOT inside coord_group):

```python
@cli.command(name="lint-spec")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
def lint_spec_cmd(spec_path: Path, fmt: str) -> None:
    """Pre-flight: validate a markdown spec for plan-readiness."""
    import dataclasses
    from harness.lint import lint_spec, is_plan_ready

    findings = lint_spec(spec_path)
    ready = is_plan_ready(findings)

    if fmt == "json":
        click.echo(json.dumps({
            "spec_path": str(spec_path),
            "plan_ready": ready,
            "findings": [dataclasses.asdict(f) for f in findings],
        }, indent=2))
    else:
        click.echo(f"spec: {spec_path}")
        click.echo(f"plan_ready: {ready}")
        for f in findings:
            click.echo(f"  [{f.severity}] {f.code}: {f.message}")
        if not findings:
            click.echo("  (no findings)")

    # Exit 1 if any error-severity finding exists; exit 0 on warn-only / clean
    sys.exit(0 if ready else 1)
```

### 3. Tests

`tests/test_lint.py`:

```python
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
        "# spec\n\nLong-enough body that has\nmultiple lines but no\nacceptance section\n"))
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
```

## Acceptance

- `python -m pytest tests/test_lint.py` — green.
- Full suite stays green.
- `harness lint-spec --help` shows the new top-level verb (NOT under coord).

## Constraints

- DO NOT touch coord_group block in cli.py.
- DO NOT touch any other module — pure new code + one CLI addition.
- Stdlib only (re + pathlib).
- Keep lint.py under 100 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
