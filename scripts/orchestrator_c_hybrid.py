"""Architecture C: Hybrid orchestrator — engine-fallback chain + Claude opt-in.

Composes the next spec via a fallback chain:

    1. PRIMARY: MiMo Pro (free via tp- subscription, 100% reliable for
       spec composition per W5-F)
    2. FALLBACK: DeepSeek v4-flash (cheap reasoning rescue)
    3. ESCALATION: Claude `-p` (for TODOs operator tagged
       `reasoning-heavy` in the TODO notes column)

Trade-offs vs A (Claude-only) and B (single engine):
- Pro: No single point of failure.  If MiMo glitches, DeepSeek rescues.
- Pro: Cost stays near $0 (MiMo subscription).  DeepSeek pays only on
  fallback (rare).  Claude pays only on operator escalation.
- Pro: Operator-tunable per-TODO via the notes column.
- Con: More complex to reason about; debugging which engine actually
  composed requires reading the cycle report.

Usage:
    PYTHONPATH=src python scripts/orchestrator_c_hybrid.py [--execute]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orchestrator_lib import (  # noqa: E402
    compose_spec_from_template, run_cycle,
)
from harness.engines.concrete import get_engine  # noqa: E402
from harness.memory import format_for_packet  # noqa: E402


COMPOSE_INSTRUCTIONS = """You are an autonomous orchestrator composing
a harness spec for the next TODO from the operator's backlog.

Output ONLY the spec markdown content — no prose before/after, no
markdown code fence wrapping the output.

The spec MUST follow:

# SPEC-ID: <one-line goal>

**Purpose**: <2-3 sentences>

## Goal

<3-6 sentences>

## Acceptance

1. <Machine-checkable assertion>
2. ...

## Why this spec exists

<1-2 sentences>

SAFETY: the deliverable MUST be a NEW docs file at
`coord/orchestrator-demo/<TODO-ID>.md`.  Do NOT request code changes.
"""


def _try_engine(engine_name: str, packet: str, model: str | None = None) -> tuple[bool, str, int, int]:
    """Dispatch + return (success, text, tokens_in, tokens_out).  Best-effort."""
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
        resp = eng.dispatch(packet, model or "", {})
        ok = bool(resp.success and (resp.text or "").strip())
        return (ok, resp.text or "",
                getattr(resp, "tokens_in", 0),
                getattr(resp, "tokens_out", 0))
    except Exception:
        return (False, "", 0, 0)


def _maybe_strip_md_fence(text: str) -> str:
    """If engine wrapped output in ``` fences, strip them."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def hybrid_composer(todo, spec_dir: Path) -> tuple[Path, str, float]:
    """Try MiMo -> DeepSeek -> (optional Claude -p) -> template fallback."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"auto-{todo.id.lower()}.md"

    memory_block = format_for_packet(max_total_bytes=8000)
    packet = "\n".join([
        memory_block,
        "\n---\n",
        COMPOSE_INSTRUCTIONS,
        f"\n## TODO row\n",
        f"- id: {todo.id}",
        f"- title: {todo.title}",
        f"- category: {todo.category}",
        f"- notes: {todo.notes}",
    ])

    # Check if operator escalated this TODO to Claude
    reasoning_heavy = "reasoning-heavy" in (todo.notes or "").lower()

    if reasoning_heavy and shutil.which("claude") is not None:
        # Skip straight to Claude -p
        claude_prompt = (
            "Operator tagged this TODO as reasoning-heavy.  Compose "
            "a harness spec following the operator's conventions in "
            "memory/spec-composition.md.\n\n" + packet
            + f"\n\nWrite the spec to {spec_path}.  Output ONLY the file.")
        proc = subprocess.run(["claude", "-p", claude_prompt, "--bare"],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode == 0 and spec_path.exists():
            return spec_path, "claude-p (escalation)", 0.0
        # else fall through to engine chain

    # Try MiMo Pro
    ok, text, tin, tout = _try_engine("mimo", packet, "mimo-v2.5-pro")
    if ok:
        spec_path.write_text(_maybe_strip_md_fence(text), encoding="utf-8")
        return spec_path, "mimo/mimo-v2.5-pro (primary)", 0.0

    # Fallback: DeepSeek
    ok, text, tin, tout = _try_engine("deepseek", packet, "deepseek-v4-flash")
    if ok:
        spec_path.write_text(_maybe_strip_md_fence(text), encoding="utf-8")
        from harness.budget import _compute_cost as _cost
        cost = _cost("deepseek", tin, tout)
        return spec_path, "deepseek/v4-flash (fallback)", cost

    # Last resort: template
    compose_spec_from_template(todo, spec_dir)
    return spec_path, "template (all engines failed)", 0.0


def main() -> int:
    execute = "--execute" in sys.argv
    print(f"=== Architecture C: Hybrid orchestrator (execute={execute}) ===",
          flush=True)
    print("  chain: MiMo -> DeepSeek -> Claude (if reasoning-heavy) -> template",
          flush=True)
    result = run_cycle("C", hybrid_composer, execute=execute)
    print(f"\nResult: TODO={result.todo_id} composer={result.composer_engine} "
          f"cost=${result.composer_cost_usd:.4f} "
          f"executed={result.executed} outcome={result.execution_outcome}",
          flush=True)
    return 0 if result.composer_engine != "n/a" else 1


if __name__ == "__main__":
    raise SystemExit(main())
