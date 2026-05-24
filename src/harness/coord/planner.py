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

_PLANNER_SCHEMA_EXAMPLE = """\
{
  "schema_version": 1,
  "run_id": "<provided>",
  "spec_path": "<provided>",
  "created_at": "<iso8601 UTC>",
  "planner_engine": "kimi",
  "tasks": [
    {
      "worker_id": "worker-1",
      "title": "Short imperative title",
      "description": "What this worker accomplishes",
      "steps": [
        {
          "step_id": "s1",
          "kind": "edit",
          "instruction": "What the worker does in this step",
          "target_files": ["relative/path"],
          "expected_diff_lines": 10,
          "required_tests": []
        }
      ],
      "write_set": ["relative/path"],
      "read_set": ["relative/path"],
      "test_set": [],
      "depends_on": [],
      "estimated_kimi_minutes": 10,
      "max_context_tokens": 30000
    }
  ],
  "integration_strategy": "squash",
  "notes": ""
}

Field rules:
- `tasks` must be 1-24 items. Each `worker_id` matches `^worker-\\d+$`.
- Each task's `steps` must be 1-15 items. `step_id` is short (max 64).
- `kind` is one of: edit, create, delete, test, shell.
- `write_set` lists files this worker mutates (DISJOINT across tasks).
- `read_set` lists files this worker reads.
- `target_files` and `expected_diff_lines` are required per step.
- `depends_on` is empty when the task can run in parallel.
- `planner_engine` is one of: claude, kimi, kimi-api, deepseek, mock.
- `integration_strategy` is one of: squash, merge, rebase.
"""

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

# Schema (compact example — match shape exactly, fill placeholders)
{schema_excerpt}

# Output
Emit ONLY a valid WavePlan JSON object, with all required fields populated.
Wrap in a ```json fenced block.
"""


def _new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    salt = secrets.token_hex(2)
    return f"{ts}-{salt}"


def _extract_single_worker_directive(spec_text: str) -> bool:
    """W7-SPEC-DRIFT 2026-05-23: detect the operator's
    "must be done by ONE worker" directive in a spec.

    Two recognised forms:

    1. Structured directive in a ``## Planner Guidance`` section:

           ## Planner Guidance
           - single_worker: true

    2. Free-form sentence (case-insensitive):

           **This change MUST be done by ONE worker...**

    The directive exists because multi-worker plans risk cross-worker
    contract drift: worker-1 implements A while worker-2 writes tests
    against B (discovered during W6-A1 — different short labels vs
    full names + an extra API key).  When the operator wants tight
    coupling (e.g. tests + implementation in one file pair), they
    declare it; the planner is required to honor it.

    Returns ``True`` if any recognised form is present.
    """
    # Form 2: free-form sentence pattern.  Liberal regex — handle
    # bold markdown wrapping + various phrasings ("by ONE worker",
    # "by a single worker", "in ONE worker").
    free_form = re.compile(
        r"(?i)must\s+be\s+done\s+(?:by|in)\s+(?:one|a\s+single)\s+worker",
    )
    if free_form.search(spec_text):
        return True
    # Form 1: structured directive.  Locate "## Planner Guidance"
    # header (case-insensitive) and scan the section body for
    # ``single_worker: true`` (with optional surrounding whitespace
    # or markdown list bullets).
    header_re = re.compile(r"(?im)^##\s+planner[_\s]*guidance\s*$")
    m = header_re.search(spec_text)
    if not m:
        return False
    section_start = m.end()
    next_header = re.search(r"(?m)^##\s+", spec_text[section_start:])
    section_end = (
        section_start + next_header.start() if next_header
        else len(spec_text)
    )
    section_body = spec_text[section_start:section_end]
    structured = re.compile(
        r"(?im)single_worker\s*:\s*true",
    )
    return bool(structured.search(section_body))


def _extract_strict_paths(spec_text: str) -> list[str]:
    """Parse a `## Strict Paths` section from the spec markdown.

    W5-BB 2026-05-23: Phase 3 validation showed the worker deviated
    from a spec's explicit path (asked for ``coord/orchestrator-demo/``,
    wrote to ``coord/postmortems/``).  When the operator wants
    deterministic output paths, they declare them in a `## Strict
    Paths` (or `## STRICT_PATHS`) section as a markdown bullet list:

        ## Strict Paths
        - coord/orchestrator-demo/2026-05-22T094327Z.md
        - coord/orchestrator-demo/2026-05-22T094327Z.json

    The planner extracts these and overrides whatever the LLM emits
    for ``strict_paths``, so the operator's declaration is binding.
    Returns ``[]`` when no section is present.
    """
    # Match the header (case-insensitive, optional underscore variants)
    header_re = re.compile(
        r"(?im)^##\s+strict[_\s]*paths\s*$",
    )
    m = header_re.search(spec_text)
    if not m:
        return []
    # Slice from end of header to end of section (next `##` header or EOF)
    section_start = m.end()
    next_header = re.search(r"(?m)^##\s+", spec_text[section_start:])
    section_end = (
        section_start + next_header.start() if next_header else len(spec_text)
    )
    section = spec_text[section_start:section_end]
    # Extract bullet-list items: lines starting with `- ` or `* `
    paths: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_bullet = re.match(r"^[-*]\s+(.+?)\s*$", stripped)
        if m_bullet:
            paths.append(m_bullet.group(1).strip("`\"' "))
    return paths


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
    # WIRE-RUN-ID-AUTOGEN (2026-05-22): the WavePlan schema enforces
    # ``^\d{8}T\d{6}-[a-z0-9]{4}$`` on run_id (timestamp + 4-char suffix).
    # Operators occasionally pass a free-form label and get a cryptic
    # pydantic pattern-mismatch error.  Auto-generate when missing OR
    # malformed; emit a clear warning so the operator sees the synthesis.
    import re as _re_run_id
    _RUN_ID_RE = _re_run_id.compile(r"^\d{8}T\d{6}-[a-z0-9]{4}$")
    if not run_id or not _RUN_ID_RE.match(run_id):
        old = run_id
        run_id = _new_run_id()
        if old:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "planner: run_id %r does not match required pattern "
                "^<YYYYMMDDTHHMMSS>-<4 lowercase hex>$; using auto-generated %r instead.",
                old, run_id,
            )
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
    # W7-SPEC-DRIFT 2026-05-23: detect operator's single-worker
    # directive so we can both nudge the LLM via the prompt AND
    # enforce post-hoc on the generated plan.
    single_worker_required = _extract_single_worker_directive(spec_text)
    # Battle-test 2026-05-21: `WavePlan.model_json_schema()` produces a
    # 4.8 KB nested JSON schema that overwhelmed Kimi Code (server
    # disconnect mid-response).  A hand-rolled compact example with
    # field rules gives the LLM the same structural guidance in ~1.5 KB
    # and gets clean JSON back.
    prompt = PLANNER_PROMPT_TEMPLATE.format(
        spec_text=spec_text,
        repo_tree=repo_tree,
        schema_excerpt=_PLANNER_SCHEMA_EXAMPLE,
    )
    if single_worker_required:
        # Prepend a hard directive at the top of the prompt so the LLM
        # sees it before reading the schema example (which shows 2
        # tasks).  Post-hoc validation catches LLMs that ignore this.
        prompt = (
            "# OPERATOR DIRECTIVE — SINGLE-WORKER REQUIRED\n\n"
            "The spec below explicitly requires this change to be done\n"
            "by ONE worker (either via `single_worker: true` in a\n"
            "## Planner Guidance section, or via a 'MUST be done by\n"
            "ONE worker' sentence in the body).  Emit EXACTLY 1 entry\n"
            "in `tasks[]`.  Splitting across workers will be rejected.\n\n"
            f"{prompt}"
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
        # W5-EE 2026-05-23: dispatch_packet's force_engine accepts only
        # raw concrete-engine names ("kimi", "deepseek", "anthropic",
        # "mimo", "mock", "gemini"); planner verb accepts the broader
        # swarm-prefixed taxonomy ("kimi-api", "claude", etc.).  Map
        # planner names to dispatcher names so --engine kimi-api works.
        _PLANNER_TO_DISPATCH = {
            "kimi-api": "kimi",  # both hit the same Kimi HTTP API
        }
        dispatch_engine = _PLANNER_TO_DISPATCH.get(engine, engine)
        try:
            result = dispatch_packet(
                project="harness-planner",
                packet_path=tmp_path,
                force_engine=dispatch_engine if dispatch_engine != "claude" else None,
                force_model=model,
                # WIRE-TRUSTED-SOURCE (2026-05-22): operator-authored
                # specs routinely reference DPAPI/env-var APIs by name
                # in code-fence prose (e.g. spec/samples/env-doctor-*).
                # The injection filter is for relayed engine output, not
                # operator ingress — exempt the planner.
                trusted_source=True,
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
        # W5-BB 2026-05-23: operator-declared strict_paths override any
        # LLM-emitted value.  The spec is the binding source.
        operator_strict_paths = _extract_strict_paths(spec_text)
        if operator_strict_paths:
            data["strict_paths"] = operator_strict_paths
        try:
            plan_obj = WavePlan.model_validate(data)
        except ValidationError as exc:
            last_error = exc
            # Add the validation error as feedback in next retry's prompt
            prompt = (
                f"{prompt}\n\n# Previous attempt failed validation:\n{exc}\n"
                f"# Fix the issues and re-emit.\n"
            )
            continue
        # W7-SPEC-DRIFT 2026-05-23: post-hoc single-worker enforcement.
        # If the operator declared single_worker required and the LLM
        # still emitted multiple tasks, reject this attempt and retry
        # with explicit feedback.  This is the safety net behind the
        # prompt-level directive — LLMs occasionally ignore even
        # explicit instructions.
        if single_worker_required and len(plan_obj.tasks) != 1:
            last_error = ValueError(
                "spec declared single_worker required, but planner "
                f"emitted {len(plan_obj.tasks)} tasks.  This is the "
                "W7-SPEC-DRIFT class of failure: cross-worker contract "
                "drift caused W6-A1's initial run to produce "
                "incompatible test+implementation files."
            )
            prompt = (
                f"{prompt}\n\n# Previous attempt violated single-worker "
                f"directive (emitted {len(plan_obj.tasks)} tasks; "
                "operator requires EXACTLY 1).  Re-emit with all the "
                "work folded into one tasks[] entry — combine write_set, "
                "read_set, and steps into a single worker.\n"
            )
            continue
        return plan_obj

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
