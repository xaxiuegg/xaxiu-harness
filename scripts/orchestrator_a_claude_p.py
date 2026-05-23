"""Architecture A: Claude `-p` cron driver as orchestrator.

Composes the next spec by shelling out to `claude -p` (headless Claude
Code mode).  Uses the operator's existing Claude subscription via
CLAUDE_CODE_OAUTH_TOKEN OR interactive login — whichever is configured.

ToS note: `claude -p` IS Claude Code, so it's allowed.  The only ToS
risk is if `claude -p` invocations explicitly drive a multi-engine
harness in ways that look like "third-party tool" use.  This script
keeps the Claude call narrow: ONE prompt → ONE spec output.  Worker
dispatch happens outside Claude.

Usage:
    PYTHONPATH=src python scripts/orchestrator_a_claude_p.py [--execute]

--execute fires the actual `coord run` after composing the spec.
Without it, the script just demonstrates the composition step.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from orchestrator_lib import (  # noqa: E402
    CycleResult, compose_spec_from_template, run_cycle,
)


def claude_p_composer(todo, spec_dir: Path) -> tuple[Path, str, float]:
    """Invoke `claude -p` with a spec-composition prompt.

    The prompt instructs Claude to produce a spec markdown for the
    TODO and write it to the given path.  Claude `-p` runs as a
    one-shot non-interactive session.

    Returns (spec_path, engine_label, cost_estimate).  Cost is $0
    since `claude -p` draws from subscription credit pool (June 15
    2026: separate Agent SDK monthly credit).
    """
    if shutil.which("claude") is None:
        # Fallback: template composer.  Allows the demo to run even
        # without claude CLI installed; logs the gap.
        spec_path = compose_spec_from_template(todo, spec_dir)
        return spec_path, "claude-cli-missing-fallback-template", 0.0

    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"auto-{todo.id.lower()}.md"

    prompt = f"""Compose a harness spec markdown for this TODO and write
it to {spec_path}.

TODO id: {todo.id}
TODO title: {todo.title}
TODO category: {todo.category}
TODO notes: {todo.notes}

The spec MUST follow memory/spec-composition.md exactly (read it first
via `Read memory/spec-composition.md`).  Output ONLY the markdown spec
to the file; do not also print prose to me.  Use the spec template
sections: # SPEC-ID, **Purpose**, ## Goal, ## Acceptance, ## Why this
spec exists.

Acceptance criteria MUST be machine-checkable (file-exists / contains
/ regex / exit-code-zero).  Keep the scope small enough that the
worker can complete in 1-2 steps.

For safety in this demo: make the spec's deliverable a docs file
under coord/orchestrator-demo/ — NOT a real code change.  Specifically:
the spec should ask the worker to create coord/orchestrator-demo/{todo.id}.md
with a short status note.
"""

    proc = subprocess.run(
        ["claude", "-p", prompt, "--bare"],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0 or not spec_path.exists():
        # Fallback to template
        compose_spec_from_template(todo, spec_dir)
        return spec_path, f"claude-p-failed-rc={proc.returncode}-fallback-template", 0.0

    return spec_path, "claude -p", 0.0


def main() -> int:
    execute = "--execute" in sys.argv
    print(f"=== Architecture A: Claude -p orchestrator (execute={execute}) ===",
          flush=True)
    result = run_cycle("A", claude_p_composer, execute=execute)
    print(f"\nResult: TODO={result.todo_id} composer={result.composer_engine} "
          f"executed={result.executed} outcome={result.execution_outcome}",
          flush=True)
    return 0 if result.composer_engine != "n/a" else 1


if __name__ == "__main__":
    raise SystemExit(main())
