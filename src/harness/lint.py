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
