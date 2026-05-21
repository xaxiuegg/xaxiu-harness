# Packet: v2/B — Coordinator JSON schemas + Planner module

## Mission

Per `spec/multi-agent-harness-architecture.md` §3.2 + §4: define the four cross-process JSON contracts (WavePlan, WorkerTask, WorkerStep, WorkerResult, RunState) as Pydantic models, plus the Planner module that turns a markdown spec into a `WavePlan` via the engine.

This is the IPC layer. Workers (v2/C) and Coordinator (v2/D) both depend on these schemas. Land first; v2/C and v2/D may dispatch in parallel after this lands.

## In-scope NEW files

- `src/harness/coord/__init__.py` — re-exports
- `src/harness/coord/schemas.py` — Pydantic models per spec §4 (WavePlan, WorkerTask, WorkerStep, WorkerResult, RunState, WorkerStatus, IntegratorStatus, Escalation, TestSummary)
- `src/harness/coord/planner.py` — `plan(spec_path, run_id, engine='claude', model=None) -> WavePlan`
- `tests/test_coord_schemas.py` — schema validation tests
- `tests/test_coord_planner.py` — planner happy path + retry + validation failure

## In-scope MODIFY files

NONE.  CLI wiring lands in v2/D.

## Schemas (src/harness/coord/schemas.py)

Match the architecture spec §4 verbatim. Field constraints + extra="forbid" everywhere.

```python
from __future__ import annotations
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RunStateLiteral(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    INTEGRATING = "integrating"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class WorkerStateLiteral(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REPLAN = "needs_replan"
    PARTIAL = "partial"


class WorkerStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=64)
    kind: Literal["edit", "create", "delete", "test", "shell"]
    instruction: str = Field(min_length=1, max_length=4000)
    target_files: list[str] = Field(default_factory=list, max_length=20)
    expected_diff_lines: int = Field(ge=0, le=2000)
    required_tests: list[str] = Field(default_factory=list, max_length=10)


class WorkerTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(pattern=r"^worker-\d+$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    read_set: list[str] = Field(default_factory=list, max_length=50)
    write_set: list[str] = Field(default_factory=list, max_length=20)
    test_set: list[str] = Field(default_factory=list, max_length=10)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    steps: list[WorkerStep] = Field(default_factory=list, max_length=15)
    estimated_kimi_minutes: int = Field(ge=1, le=60, default=10)
    max_context_tokens: int = Field(ge=1000, le=100000, default=30000)


class WavePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str = Field(pattern=r"^\d{8}T\d{6}-[a-z0-9]{4}$")
    spec_path: str = Field(min_length=1, max_length=512)
    created_at: str
    planner_engine: Literal["claude", "kimi", "kimi-api", "deepseek"]
    planner_model: str | None = Field(default=None, max_length=128)
    tasks: list[WorkerTask] = Field(min_length=1, max_length=24)
    integration_strategy: Literal["squash", "merge", "rebase"] = "squash"
    notes: str = Field(default="", max_length=2000)


class TestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ran: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0, default=0)
    duration_seconds: float = Field(ge=0.0)


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    worker_id: str = Field(pattern=r"^worker-\d+$")
    run_id: str
    state: WorkerStateLiteral
    started_at: str
    finished_at: str | None = None
    steps_completed: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list, max_length=50)
    test_summary: TestSummary
    commit_sha: str | None = Field(default=None, pattern=r"^[a-f0-9]{7,40}$")
    error_tag: str | None = Field(default=None, max_length=64)
    diagnostic: str = Field(default="", max_length=4000)
    tokens_used: int = Field(ge=0, default=0)
    elapsed_seconds: int = Field(ge=0, default=0)


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str
    state: WorkerStateLiteral
    last_checkpoint_at: str | None = None
    last_step_id: str | None = None
    pid: int | None = None


class IntegratorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["pending", "merging", "testing", "committing", "pushing", "done", "failed"]
    last_action: str = ""
    last_action_at: str | None = None
    commit_sha: str | None = None


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    level: Literal["L1", "L2", "L3", "L4", "L5"]
    tag: str
    raised_at: str
    diagnostic: str = ""
    affected_workers: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: str
    spec_path: str
    state: RunStateLiteral
    plan_path: str
    started_at: str
    last_tick_at: str
    workers: dict[str, WorkerStatus] = Field(default_factory=dict)
    integrator_status: IntegratorStatus | None = None
    escalations: list[Escalation] = Field(default_factory=list)
```

## Planner module (src/harness/coord/planner.py)

```python
from __future__ import annotations
import json
import re
import tempfile
import secrets
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
```

For tests, mock `dispatch_packet` to return a known good JSON string. Don't actually call the engine in tests.

## Tests required

schemas (test_coord_schemas.py): 12+
- WavePlan rejects: missing run_id, invalid run_id pattern, 0 tasks, 25 tasks (over max)
- WorkerTask rejects: bad worker_id format, missing required fields, oversized write_set
- WorkerStep rejects: unknown kind, oversized instruction
- WorkerResult rejects: bad commit_sha pattern, conflicting states
- All schemas: extra fields rejected (extra="forbid")
- All schemas: round-trip through model_dump_json + model_validate_json preserves data

planner (test_coord_planner.py): 6+
- Happy path (mock dispatch_packet returns valid JSON in code fence)
- JSON without code fence still extracted
- Retry on validation error succeeds on attempt #2
- ValidationError raised after exhausting retries
- run_id auto-generated if not provided (pattern \d{8}T\d{6}-[a-z0-9]{4})
- write_plan writes file atomically

Target ≥18 new tests.

## Acceptance criteria

1. `from harness.coord.schemas import WavePlan, WorkerTask` works.
2. `WavePlan.model_validate({...minimal valid dict...})` succeeds.
3. `from harness.coord.planner import plan` works (don't actually call it in CI; mocked).
4. `python -m pytest tests/ -q` shows ≥627 + 18 new tests, all green.
5. Single commit: `feat(coord): WavePlan/WorkerTask/WorkerResult schemas + Planner module (v2/B)`.

## Reference

- `spec/multi-agent-harness-architecture.md` §3.2 and §4 (canonical design)
- `src/harness/adapters/schema.py` — Pydantic v2 pattern reference (ConfigDict, extra="forbid")
- `src/harness/status/schema.py` — sibling Pydantic module
- `src/harness/engines/dispatcher.py::dispatch_packet` — planner invokes this

## Output format

5 new files + 0 modifications + 1 commit. No cli.py changes (those land in v2/D).
