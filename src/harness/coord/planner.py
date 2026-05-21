"""Planner module: turn a markdown spec into a ``WavePlan`` via the engine."""

from __future__ import annotations

import json
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from harness.coord.schemas import WavePlan

PLANNER_PROMPT_TEMPLATE = """\
SYSTEM: You are the planner for a multi-agent dev harness. Given the
spec below, decompose into 1-12 independent worker tasks. Each task
must touch a DISJOINT set of files (you will list them in `write_set`).
Tasks may declare dependencies via `depends_on`. Emit a single JSON
object matching the WavePlan schema. No prose, no commentary outside
the JSON.

# Spec (markdown)
{spec_text}

# Repo inventory (top-level files, truncated)
{repo_tree}

# Schema (reference — match exactly)
{schema_excerpt}

# Output
Emit ONLY a valid WavePlan JSON object, with all required fields populated.
"""


def _new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    salt = secrets.token_hex(2)
    return f"{ts}-{salt}"


def _read_repo_tree(root: Path, max_lines: int = 200) -> str:
    """Return a truncated repo file tree for the planner context."""
    lines: list[str] = []
    for p in sorted(root.rglob("*"))[:1000]:
        if p.is_dir() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        lines.append(f"{p.relative_to(root)!s:60} {size}")
        if len(lines) >= max_lines:
            lines.append(f"... (truncated; {len(lines)}+ files)")
            break
    return "\n".join(lines)


def plan(
    spec_path: Path,
    *,
    run_id: str | None = None,
    engine: str = "claude",
    model: str | None = None,
    project_root: Path | None = None,
    max_retries: int = 1,
) -> WavePlan:
    """Decompose the markdown spec at *spec_path* into a WavePlan.

    Raises ValidationError if every retry fails the schema check.
    """
    run_id = run_id or _new_run_id()
    spec_text = Path(spec_path).read_text(encoding="utf-8")
    root = project_root or Path.cwd()
    repo_tree = _read_repo_tree(root)
    prompt = PLANNER_PROMPT_TEMPLATE.format(
        spec_text=spec_text,
        repo_tree=repo_tree,
        schema_excerpt=WavePlan.model_json_schema(),
    )

    # Dispatch via harness.engines.dispatcher
    from harness.engines.dispatcher import dispatch_packet

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        # write prompt to a temp packet file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(prompt)
            tmp_path = tmp.name
        try:
            result = dispatch_packet(
                project="harness-planner",
                packet_path=tmp_path,
                force_engine=engine if engine != "claude" else None,
                force_model=model,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        if not result.success:
            last_error = RuntimeError(
                f"planner dispatch failed: {result.error}"
            )
            continue
        # Extract JSON from response (model may wrap in code fences)
        raw = result.text.strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            last_error = ValueError("planner output contained no JSON object")
            continue
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        # Ensure run_id is what we expect
        data["run_id"] = run_id
        data["created_at"] = datetime.now(timezone.utc).isoformat()
        data["planner_engine"] = engine if engine != "claude" else "claude"
        data["spec_path"] = str(spec_path)
        try:
            return WavePlan.model_validate(data)
        except ValidationError as exc:
            last_error = exc
            # Add the validation error as feedback in next retry's prompt
            prompt = (
                f"{prompt}\n\n# Previous attempt failed validation:\n{exc}\n"
                f"# Fix the issues and re-emit.\n"
            )
            continue

    assert last_error is not None
    raise last_error


def write_plan(plan_obj: WavePlan, run_dir: Path) -> Path:
    """Write the plan to runs/<run_id>/plan.json atomically."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "plan.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(plan_obj.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
