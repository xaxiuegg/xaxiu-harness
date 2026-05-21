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
    skip_lint: bool = False,
) -> WavePlan:
    """Decompose the markdown spec at *spec_path* into a WavePlan.

    WIRE-AUTOLINT (2026-05-21): unless ``skip_lint=True``, the spec is
    passed through ``harness.lint.lint_spec`` first.  If any finding has
    severity 'error', planning is refused (raising ValueError with the
    finding messages) so the operator never burns engine tokens on a
    spec that wasn't ready.

    Raises ValidationError if every retry fails the schema check, or
    ValueError if the spec fails its preflight lint.
    """
    run_id = run_id or _new_run_id()
    if not skip_lint:
        try:
            from harness.lint import lint_spec, is_plan_ready
        except ImportError:
            pass  # lint module missing — defer to old behaviour
        else:
            findings = lint_spec(Path(spec_path))
            if not is_plan_ready(findings):
                errs = "; ".join(
                    f"{f.code}: {f.message}" for f in findings if f.severity == "error"
                )
                raise ValueError(f"spec lint failed: {errs}")
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


def plan_from_description(
    description: str,
    *,
    run_id: str | None = None,
    engine: str = "claude",
    model: str | None = None,
    project_root: Path | None = None,
    max_retries: int = 1,
) -> WavePlan:
    """Decompose a natural-language description into a WavePlan.

    Writes the description to a temp .md file and delegates to plan().
    Keeps wrapper logic small so callers (the new CLI verb) stay tiny.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(f"# Task (from natural language)\n\n{description}\n")
        tmp_path = Path(tmp.name)
    try:
        return plan(
            tmp_path,
            run_id=run_id,
            engine=engine,
            model=model,
            project_root=project_root,
            max_retries=max_retries,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def replan_from_run(
    failed_run_dir: Path,
    *,
    engine: str = "claude",
    model: str | None = None,
    project_root: Path | None = None,
    new_run_id: str | None = None,
) -> WavePlan:
    """Re-run the planner with failed-worker feedback from a prior run.

    Reads ``failed_run_dir/plan.json`` (for the original spec_path) plus all
    checkpoint files under ``failed_run_dir/checkpoints/`` to build a
    feedback section, then calls :func:`plan` with an augmented prompt
    that includes the failed workers' diagnostics.

    Returns a NEW :class:`WavePlan` with a fresh run_id.

    Raises:
        FileNotFoundError: If plan.json doesn't exist.
        ValidationError: If the regenerated plan still fails schema check.
    """
    failed_run_dir = Path(failed_run_dir)
    plan_path = failed_run_dir / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"no plan.json at {plan_path}")

    old_plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    spec_path = Path(old_plan.spec_path)
    if not spec_path.exists():
        raise FileNotFoundError(f"original spec not found at {spec_path}")

    # Gather failed-worker diagnostics
    failures: list[str] = []
    ckpt_dir = failed_run_dir / "checkpoints"
    if ckpt_dir.exists():
        for ckpt_path in sorted(ckpt_dir.glob("*.json")):
            try:
                data = json.loads(ckpt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("state") == "failed":
                wid = data.get("worker_id", "?")
                diag = data.get("tests_summary") or data.get("diagnostic") or "unknown"
                failures.append(f"- {wid}: {diag}")

    # Build augmented spec text
    augmented = spec_path.read_text(encoding="utf-8")
    if failures:
        augmented += (
            "\n\n## Replan feedback (from prior failed run "
            f"{old_plan.run_id})\n\n"
            "The previous plan produced these worker failures — please "
            "decompose differently to avoid them:\n\n"
            + "\n".join(failures)
            + "\n"
        )

    # Write augmented spec to a temp file so the planner picks it up
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(augmented)
        tmp_path = Path(tmp.name)
    try:
        return plan(
            tmp_path,
            run_id=new_run_id,
            engine=engine,
            model=model,
            project_root=project_root,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def write_plan(plan_obj: WavePlan, run_dir: Path) -> Path:
    """Write the plan to runs/<run_id>/plan.json atomically."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "plan.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(plan_obj.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
