"""Architecture B: Single non-Claude engine as orchestrator.

Composes the next spec by HTTP dispatch to one engine (default
DeepSeek, since W5-F showed it has strongest reasoning).  No fallback —
this is the simplest "one engine takes over" architecture.

Trade-offs vs Claude `-p` (Arch A):
- Pro: NO ToS concern.  Pure HTTP API call.
- Pro: Deterministic billing (~$0.001-0.005 per spec composition).
- Pro: Works without Claude Code subscription.
- Con: Less reasoning depth than Opus 4.7.
- Con: If the engine has a bad day, no rescue.

Usage:
    PYTHONPATH=src python scripts/orchestrator_b_single_engine.py \\
        [--engine deepseek] [--execute]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orchestrator_lib import (  # noqa: E402
    compose_spec_from_template, run_cycle,
)
from harness.engines.concrete import get_engine  # noqa: E402
from harness.memory import format_for_packet  # noqa: E402

# Default model per engine — mirror dispatcher._ENGINE_DEFAULT_MODELS
_ENGINE_DEFAULT_MODELS = {
    "kimi":      "kimi-for-coding",
    "deepseek":  "deepseek-v4-flash",
    "anthropic": "claude-sonnet-4-5-20250929",
    "gemini":    "gemini-2.0-flash",
    "mimo":      "mimo-v2.5-pro",  # explicit for orchestrator clarity
    "mock":      "mock-model",
}


COMPOSE_INSTRUCTIONS = """You are an autonomous orchestrator composing
a harness spec for the next TODO from the operator's backlog.

Output ONLY the spec markdown content — no prose before/after, no
markdown code fence wrapping the output, just the raw spec body.

The spec MUST follow this exact shape:

# SPEC-ID: <one-line goal>

**Purpose**: <2-3 sentences>

## Goal

<3-6 sentences describing what should change>

## Acceptance

1. <Machine-checkable assertion>
2. <File X contains text Y or exit code zero or regex match>
3. ...

## Why this spec exists

<1-2 sentences linking to STATUS.csv row>

For SAFETY in this orchestrator demo: the spec's deliverable MUST be a
NEW docs file at `coord/orchestrator-demo/<TODO-ID>.md` containing the
TODO id + title + 2-3 lines.  Do NOT request any code changes.  Do NOT
edit existing files except creating that one docs file.
"""


def make_composer(engine_name: str, model: str | None):
    """Build a composer callable for the given engine."""

    def composer(todo, spec_dir: Path) -> tuple[Path, str, float]:
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_path = spec_dir / f"auto-{todo.id.lower()}.md"

        # Build the dispatch packet
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

        eng = get_engine(engine_name, prefer_dpapi=False)
        effective_model = model or _ENGINE_DEFAULT_MODELS.get(engine_name, "")
        resp = eng.dispatch(packet, effective_model, {})
        if not resp.success or not (resp.text or "").strip():
            # Fallback to template baseline
            compose_spec_from_template(todo, spec_dir)
            return spec_path, f"{engine_name}-failed-fallback-template", 0.0

        # Strip optional ``` markdown fence wrapper
        text = (resp.text or "").strip()
        if text.startswith("```"):
            # Find closing fence
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Strip trailing fence
            while lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)

        spec_path.write_text(text, encoding="utf-8")

        # Cost estimate from W4-K tokens (best-effort)
        from harness.budget import _compute_cost as _cost
        try:
            tokens_in = getattr(resp, "tokens_in", 0)
            tokens_out = getattr(resp, "tokens_out", 0)
            cost = _cost(engine_name, tokens_in, tokens_out)
        except Exception:
            cost = 0.0
        return spec_path, f"{engine_name}/{model or 'default'}", cost

    return composer


def main() -> int:
    args = sys.argv[1:]
    execute = "--execute" in args
    engine_name = "deepseek"
    model = None
    if "--engine" in args:
        idx = args.index("--engine")
        engine_name = args[idx + 1]
    if "--model" in args:
        idx = args.index("--model")
        model = args[idx + 1]

    print(f"=== Architecture B: Single-engine orchestrator "
          f"(engine={engine_name}, execute={execute}) ===", flush=True)
    composer = make_composer(engine_name, model)
    result = run_cycle("B", composer, execute=execute)
    print(f"\nResult: TODO={result.todo_id} composer={result.composer_engine} "
          f"cost=${result.composer_cost_usd:.4f} "
          f"executed={result.executed} outcome={result.execution_outcome}",
          flush=True)
    return 0 if result.composer_engine != "n/a" else 1


if __name__ == "__main__":
    raise SystemExit(main())
