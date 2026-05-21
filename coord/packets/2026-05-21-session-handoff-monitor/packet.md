# Packet: Session-handoff monitor

## Mission

Implement the session-handoff monitor per `spec/session-handoff-monitor.md`. Operator-facing feature: the dev manager proactively detects when a Claude session should be transferred (context drift, memory pressure, accumulated context-rot risk) and generates a self-contained "master prompt" that boots a fresh session with the current state baked in.

Brief: "Alongside an L5 error, monitor the JSON file of a session and alert the user. If they agree, create a master prompt. If not, re-alert when resource pressure suggests a crash."

Disjoint from v2/A (which lives in `harness/proxy/`); both can land in parallel.

## In-scope NEW files

- `src/harness/session/__init__.py`
- `src/harness/session/signals.py` — psutil + filesystem signal collectors; returns a `dict[str, Any]` of measured values
- `src/harness/session/recommender.py` — `Recommendation` StrEnum (NONE / SOFT / STRONGLY / CRITICAL) + `recommend(signals) -> Recommendation` per spec §2
- `src/harness/session/bootstrap.py` — `generate_master_prompt(reason: str, state_path: Path = ...) -> str` per spec §4
- `src/harness/session/monitor.py` — `check(state_path) -> CheckReport` one-shot entrypoint
- `tests/test_session_signals.py` — psutil mocked + filesystem fixtures
- `tests/test_session_recommender.py` — threshold table coverage
- `tests/test_session_bootstrap.py` — 5-section output structure
- `tests/test_session_monitor.py` — end-to-end check + handoff-file emission

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="session")` with subcommands: `check`, `bootstrap`, `ack`, `crisis-check`, `arm-crisis-check`. ≤60 LOC; delegate logic to `harness.session.*`.
- `pyproject.toml` — append `"psutil>=5.9"` to `dependencies`.

## Schemas (src/harness/session/recommender.py)

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class Recommendation(StrEnum):
    NONE = "none"
    SOFT = "soft"
    STRONGLY = "strongly"
    CRITICAL = "critical"

class Signals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_age_hours: float = Field(ge=0.0)
    tick_count: int = Field(ge=0)
    active_dispatch_count: int = Field(ge=0)
    commits_since_session: int = Field(ge=0)
    status_csv_row_count: int = Field(ge=0)
    mem_pct: float = Field(ge=0.0, le=100.0)
    claude_rss_mb: float = Field(ge=0.0)
    cpu_pct: float = Field(ge=0.0, le=100.0)
    disk_pct_free: float = Field(ge=0.0, le=100.0)
    jsonl_log_mb: float = Field(ge=0.0)

class CheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: str
    signals: Signals
    recommendation: Recommendation
    reasons: list[str] = Field(default_factory=list)
    handoff_file_written: str | None = None
```

## Recommend logic (spec §2 — implement exactly)

```python
def recommend(s: Signals) -> tuple[Recommendation, list[str]]:
    reasons: list[str] = []
    # CRITICAL — crash imminent
    if s.mem_pct >= 95 or s.disk_pct_free < 5:
        reasons.append(f"mem_pct={s.mem_pct:.1f}% or disk_pct_free={s.disk_pct_free:.1f}%")
        return Recommendation.CRITICAL, reasons
    # STRONGLY — concrete resource pressure
    if s.mem_pct >= 85:
        reasons.append(f"mem_pct={s.mem_pct:.1f}% >= 85%")
        return Recommendation.STRONGLY, reasons
    if s.claude_rss_mb > 2048:
        reasons.append(f"claude_rss={s.claude_rss_mb:.0f}MB > 2048MB")
        return Recommendation.STRONGLY, reasons
    # SOFT — accumulated drift
    soft_signals = [
        s.session_age_hours > 4,
        s.tick_count > 50,
        s.commits_since_session > 30,
        s.status_csv_row_count > 60,
        s.jsonl_log_mb > 50,
    ]
    if sum(soft_signals) >= 3 or s.session_age_hours > 4:
        reasons.append(f"soft_signals={sum(soft_signals)}/5, age={s.session_age_hours:.1f}h")
        return Recommendation.SOFT, reasons
    return Recommendation.NONE, []
```

## Master prompt generator (spec §4)

```python
def generate_master_prompt(
    reason: str,
    state_path: Path = Path("coord/dev_loop/state.json"),
    bootstrap_path: Path = Path("coord/SESSION_BOOTSTRAP.md"),
    status_path: Path = Path("coord/STATUS.csv"),
) -> str:
    """Emit a 5-section paste-into-fresh-Claude prompt."""
    sections = []
    sections.append(f"# Session handoff — {_now_iso()}")
    sections.append(f"\nReason: {reason}\n")

    # §1 base bootstrap (durable)
    sections.append("## 1. Base bootstrap (durable, project-invariant)\n")
    if bootstrap_path.exists():
        sections.append(bootstrap_path.read_text(encoding="utf-8"))
    else:
        sections.append("_(coord/SESSION_BOOTSTRAP.md not present — using CLAUDE.md fallback)_\n")
        sections.append(Path("CLAUDE.md").read_text(encoding="utf-8"))

    # §2 state snapshot
    sections.append("\n## 2. Session state snapshot\n")
    from harness.state.inspect import render_state_json
    sections.append("```\n" + render_state_json(state_path, fmt="pretty") + "\n```\n")
    from harness.status import summary as status_summary, read_status
    counts = status_summary(status_path)
    rows = read_status(status_path)
    sections.append(f"\nSTATUS.csv summary: {', '.join(f'{n} {st.value}' for st, n in counts.items() if n)}")
    sections.append(f"Total rows: {len(rows)}\n")

    # §3 wave delta (last N commits)
    sections.append("\n## 3. Wave plan delta\n")
    import subprocess
    git_log = subprocess.run(
        ["git", "log", "--oneline", "-20"],
        capture_output=True, text=True, check=False,
    )
    sections.append("Last 20 commits:\n```\n" + git_log.stdout + "```\n")

    # §4 next-action queue
    sections.append("\n## 4. Next-action queue\n")
    sections.append("_Operator: edit this section before pasting to direct the new session._\n")
    # heuristic: surface in-flight + queued items
    sections.append("\nIn flight (from active_dispatches):\n")
    import json
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    for d in (state.get("active_dispatches") or []):
        sections.append(f"  - {d.get('task_id', '?')} ({d.get('engine', '?')}) — {d.get('packet', '?')}")
    sections.append("\nQueued (from STATUS.csv where status in queued|todo):\n")
    for r in rows:
        if r.status.value in ("queued", "todo"):
            sections.append(f"  - {r.id} — {r.title}")

    # §5 memory pointers
    sections.append("\n## 5. Memory pointers\n")
    sections.append("Load these from ~/.claude/projects/D--Projects/memory/:\n")
    sections.append("- feedback_xaxiu_harness_full_dev_authority")
    sections.append("- reference_xaxiu_harness_error_taxonomy")
    sections.append("- feedback_kimi_cli_incremental_edits")
    sections.append("- feedback_full_automation_until_wave_plan_empty")
    sections.append("- (any other memories referenced in section 3 commits)")

    return "\n".join(sections)
```

## CLI surface

```python
@cli.group(name="session")
def session_group() -> None:
    """Session-handoff monitor (proactive transfer recommendation)."""

@session_group.command(name="check")
@click.option("--quiet", is_flag=True, help="Emit only the recommendation enum value")
def session_check(quiet): ...

@session_group.command(name="bootstrap")
@click.option("--reason", default="manual", help="One-line context for the new session")
@click.option("--out", type=click.Path(path_type=Path), default=None,
              help="If set, write to file; else stdout")
def session_bootstrap_cmd(reason, out): ...

@session_group.command(name="ack")
def session_ack(): ...   # delete handoff_recommended.md / handoff_CRITICAL.md flags

@session_group.command(name="crisis-check")
def session_crisis_check(): ...   # check + windows toast on HIGH/CRITICAL

@session_group.command(name="arm-crisis-check")
def session_arm_crisis_check(): ...   # register XaxiuHarnessSessionCrisisCheck task
```

## Tests required

signals (test_session_signals.py): 5+
- psutil.virtual_memory mocked → mem_pct populated correctly
- coord/dev_loop/state.json missing → session_age_hours = 0, tick_count = 0
- coord/STATUS.csv missing → status_csv_row_count = 0

recommender (test_session_recommender.py): 8+
- mem_pct >= 95 → CRITICAL
- disk_pct_free < 5 → CRITICAL
- mem_pct >= 85 → STRONGLY
- claude_rss_mb > 2048 → STRONGLY
- 3+ soft signals → SOFT
- session_age_hours > 4 → SOFT
- All low → NONE

bootstrap (test_session_bootstrap.py): 4+
- Output contains all 5 section headers
- Reason interpolated correctly
- Missing state.json → uses fallback message

monitor (test_session_monitor.py): 4+
- CRITICAL recommendation writes coord/dev_loop/handoff_CRITICAL.md
- SOFT recommendation does NOT write flag file
- ack removes existing flag files

Target ≥21 new tests.

## Acceptance criteria

1. `harness session check` prints a `CheckReport` JSON.
2. `harness session check --quiet` prints just the enum value (e.g. `soft`).
3. `harness session bootstrap --reason="long session" --out=handoff.md` writes a 5-section markdown file.
4. Mocked memory at 96% produces CRITICAL + writes `coord/dev_loop/handoff_CRITICAL.md`.
5. `harness session ack` removes the flag file.
6. `python -m pytest tests/ -q` shows ≥526 + 21 new tests, all green.
7. Single commit: `feat(session): handoff monitor — proactive transfer recommendation`.

## Reference

- `spec/session-handoff-monitor.md` — full design with thresholds + surfacing protocol
- `coord/SESSION_BOOTSTRAP.md` — durable boot section source
- `src/harness/state/inspect.py::render_state_json` — pretty-printer reused for §2
- `src/harness/observer/scheduler.py` — pattern reference (for arm-crisis-check Task Scheduler entry)
- `src/harness/observer/flags.py` — pattern for severity-tagged flag files

## Output format

5 new module files + 4 new test files + 2 modifications (cli.py + pyproject.toml) + 1 commit. psutil added as a dependency.
