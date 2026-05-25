"""W13-CLAUDEMD-INVOCATION: ensure CLAUDE.md's recommended invocation
actually works from a clean shell.

Bug history (2026-05-25): the panel-recommended minimal resume prompt
was "Run `harness today` + `harness plan show`. Propose next action."
A fresh session pasted exactly that into Bash and got
``exit 127: harness: command not found`` because pip install -e .
hadn't been run in that shell's Python environment.

The recovery — using ``PYTHONPATH=src python -m harness ...`` — IS
what the dev shell uses (and what CLAUDE.md's own smoke test uses),
but it wasn't promoted to a prominent invocation section.  That was a
gap between "this doc is technically accurate" and "an agent following
this doc gets a working command."

This test enforces:
  1. CLAUDE.md prominently documents the always-works invocation form
     ``PYTHONPATH=src python -m harness ...``
  2. The invocation form CLAUDE.md recommends actually exits 0 against
     the live CLI (smoke test against `--help`)
  3. The two orientation commands (`today`, `plan show`) appear in
     CLAUDE.md's recommended-invocation section

Separate from ``test_docs_no_future_as_present.py`` (catches fictional
verbs) and ``test_docs_mention_all_sdk_fns.py`` (catches missing SDK
names): this gate catches "real verb shown in a form that doesn't
work for the reader's shell."
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _claudemd_text() -> str:
    assert CLAUDE_MD.is_file(), f"missing {CLAUDE_MD}"
    return CLAUDE_MD.read_text(encoding="utf-8")


def test_claudemd_exists() -> None:
    """Sanity: CLAUDE.md is present at the repo root."""
    assert CLAUDE_MD.is_file()


def test_claudemd_documents_pythonpath_invocation() -> None:
    """The always-works invocation form must be prominent in CLAUDE.md.

    A fresh agent reading the file should learn within the first 80
    lines that the working command is
    ``PYTHONPATH=src python -m harness ...`` — NOT the bare ``harness``
    console script which requires pip install -e ..
    """
    text = _claudemd_text()
    # Substring check — must appear at all
    assert "PYTHONPATH=src python -m harness" in text, (
        "CLAUDE.md must document the always-works invocation form "
        "`PYTHONPATH=src python -m harness ...` so fresh sessions "
        "don't hit `exit 127: harness: command not found`.  See "
        "the 'How to invoke the harness in THIS dev shell' section."
    )
    # Proximity check — should be early in the file (within first 80 lines)
    head = "\n".join(text.splitlines()[:80])
    assert "PYTHONPATH=src python -m harness" in head, (
        "The PYTHONPATH=src invocation note must appear within the "
        "first 80 lines of CLAUDE.md so it's visible before a fresh "
        "agent runs any commands."
    )


def test_claudemd_mentions_orientation_commands() -> None:
    """The two orientation commands (`today`, `plan show`) must
    appear in CLAUDE.md so a session-resume prompt of the form
    'run X + Y' has X and Y both findable in the project memory."""
    text = _claudemd_text()
    for cmd in ("harness today", "harness plan show"):
        assert cmd in text, (
            f"CLAUDE.md must reference `{cmd}` — it's part of the "
            f"minimal session-resume orientation."
        )


def test_claudemd_recommended_invocation_actually_works() -> None:
    """End-to-end: run the invocation form CLAUDE.md recommends and
    confirm it exits 0 with help text.

    Uses subprocess to actually exec the command — catches "the form
    in the doc is wrong" as opposed to just "the form is documented."
    """
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    # Don't leak HARNESS_* / KIMI_* / etc into the subprocess — we want
    # the bare `--help` path which doesn't need any keys.
    for k in list(env):
        if k.startswith(("HARNESS_", "KIMI_", "DEEPSEEK_", "MIMO_",
                          "ANTHROPIC_", "GEMINI_")):
            env.pop(k)
    result = subprocess.run(
        [sys.executable, "-m", "harness", "--help"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"`python -m harness --help` exited {result.returncode} — "
        f"the invocation form CLAUDE.md recommends to fresh sessions "
        f"is BROKEN.\nstderr:\n{result.stderr[:500]}"
    )
    # Help text should mention core verbs
    out = result.stdout.lower()
    for verb in ("dispatch", "review", "today", "plan", "capabilities",
                  "audit"):
        assert verb in out, (
            f"`python -m harness --help` output missing verb {verb!r}; "
            f"this CLI surface is what a fresh agent will see first."
        )
