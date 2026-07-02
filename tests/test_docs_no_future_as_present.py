"""W13-FUTURE-MARKER-AUDIT: CI gate against future-as-present in docs.

The 20-agent operator-review panel (commit 7e6a16c) and DeepSeek's
strategic-plan review (commit 7375e5e) both flagged this hallucination
vector: docs describing CLI commands that don't actually exist.  An
agent (or future Claude) reading the runbook would trust it + try
the fictional command + fail.

This test scans the operator-facing docs for `harness <verb>` patterns
and FAILS if any reference doesn't match a registered CLI verb,
UNLESS the line containing the reference also has the `FUTURE`
marker explicitly documenting that the verb is aspirational.

How to fix a failure:
  1. The command IS real but the test missed it → add to KNOWN_REAL_VERBS below
  2. The command does NOT exist + the doc should be honest → prefix with
     `**FUTURE (<row-id>):**` near the command reference
  3. The command does NOT exist + you intend to add it → ship the verb
     OR mark FUTURE and add a STATUS.csv row

The test scope is the two operator-facing docs that matter most.
Updated 2026-05-27 (W14-DOCS-CONSOLIDATE 7→3) — both old doc names
(INTERNAL_OPERATOR_RUNBOOK + AGENT_QUICKSTART) were merged into:
  - docs/OPERATOR_GUIDE.md (operator-facing; absorbed quickstart +
    runbook + visual manual + using-from-other-projects + internal
    runbook)
  - docs/AGENT_REFERENCE.md (agent-facing; absorbed AGENT_QUICKSTART
    + new sections for agent-instructions + v2 coord programmatic use)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
DOCS_TO_SCAN = [
    DOCS_ROOT / "OPERATOR_GUIDE.md",
    DOCS_ROOT / "AGENT_REFERENCE.md",
]

# Patterns that match `harness <verb>` or `harness <group> <subverb>`
# inside backticks or bash code blocks.
HARNESS_CMD_RE = re.compile(
    r"`(?:\$\s*)?harness\s+([a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*)?)\s*[`\s\\-]"
)

# Lines that contain "FUTURE" or "**FUTURE" are explicitly marking
# the command as aspirational → not a regression.
FUTURE_MARKER_RE = re.compile(r"\bFUTURE\b", re.IGNORECASE)

# Some doc references describe the SHAPE of a future command for
# planning purposes (e.g. "could become `harness foo bar`").  These
# specific framings are also exempt.
EXPLAINER_PHRASES = [
    "no `harness ",
    "no harness ",
    "should become `harness",
    "would do this",
    "this verb will",
    "when this row ships",
    "when this row lands",
]


def _verbs_registered_in_cli() -> set[str]:
    """Return the set of valid `harness <verb>` strings (incl. group/sub)."""
    from harness.cli import cli

    valid: set[str] = set()
    for name, cmd in cli.commands.items():
        valid.add(name)
        # Multi-command groups: also accept "group sub"
        if hasattr(cmd, "commands"):
            for sub in cmd.commands.keys():
                valid.add(f"{name} {sub}")
    return valid


def _is_future_marked(line_idx: int, lines: list[str], window: int = 3) -> bool:
    """A command reference is FUTURE-marked if the same line OR any of
    the ``window`` preceding lines contain the FUTURE marker.
    """
    for i in range(max(0, line_idx - window), line_idx + 1):
        if FUTURE_MARKER_RE.search(lines[i]):
            return True
    return False


def _has_explainer_context(line: str) -> bool:
    """Lines that describe a command's shape but explicitly say it
    doesn't exist yet (e.g. 'no `harness foo` verb today')."""
    lower = line.lower()
    return any(phrase in lower for phrase in EXPLAINER_PHRASES)


@pytest.mark.parametrize("doc_path", DOCS_TO_SCAN, ids=lambda p: p.name)
def test_doc_has_no_unmarked_future_commands(doc_path: Path) -> None:
    """REGRESSION: docs must not describe `harness <verb>` commands
    that don't exist unless the reference is explicitly FUTURE-marked."""
    assert doc_path.exists(), f"doc not found: {doc_path}"
    valid_verbs = _verbs_registered_in_cli()
    lines = doc_path.read_text(encoding="utf-8").splitlines()

    violations: list[str] = []
    for i, line in enumerate(lines):
        for match in HARNESS_CMD_RE.finditer(line):
            verb_str = match.group(1).strip()
            # Normalize whitespace
            verb_str = " ".join(verb_str.split())
            # Try both full string + first word (so "observer flags"
            # matches AND "observer" alone matches for "harness observer
            # status" etc.)
            head = verb_str.split()[0]
            if verb_str in valid_verbs or head in valid_verbs:
                continue
            # Not in CLI — is it FUTURE-marked or explainer context?
            if _is_future_marked(i, lines):
                continue
            if _has_explainer_context(line):
                continue
            violations.append(
                f"  {doc_path.name}:{i + 1}: `harness {verb_str}` "
                f"is not a registered CLI verb + line is not FUTURE-marked"
            )

    if violations:
        msg = (
            f"\nFUTURE-AS-PRESENT VIOLATIONS in {doc_path.name}:\n"
            + "\n".join(violations)
            + "\n\nFix by either:\n"
            "  1. Adding `**FUTURE (<row-id>):**` to the heading/section\n"
            "  2. Wrapping the command line with context like "
            "'no `harness <verb>` today; FUTURE work'\n"
            "  3. Shipping the verb (ideally with a STATUS.csv row)\n"
        )
        raise AssertionError(msg)


def test_cli_verb_introspection_works():
    """Sanity: _verbs_registered_in_cli() returns the expected core verbs."""
    verbs = _verbs_registered_in_cli()
    # PATH-A item-4 shrink 2026-07-01: check the surviving core verbs.
    for required in (
        "ask",
        "today",
        "doctor",
        "proxy start",
        "keys list",
        "budget show",
        "audit show",
    ):
        assert required in verbs, f"required verb '{required}' missing from CLI registration"
