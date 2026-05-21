# Spec: Session-handoff monitor

## Goal

Prevent silent session collapse (context-rot crash, memory exhaustion,
or accumulated context drift) by proactively monitoring the active
Claude/Kimi session and recommending a session transfer to the operator
before the failure occurs. When the operator agrees, the dev manager
generates a self-contained "master prompt" that boots a fresh session
with the current state baked in (so no chain is lost).

Operator brief 2026-05-21: "Alongside an L5 error, the dev manager
should monitor the JSON file of a session and alert the user when
it's appropriate time to start a new session. If user agrees, create
a master prompt to transfer session to new session. If not, perform
reminder again when high resource usage of computer predicts a crash."

## Design

### 1 — Health signal stack (read by every dev-manager tick)

| Signal | Source | Threshold | Severity |
|---|---|---|---|
| Session age | `state.json::started_at` vs now | > 4 h | SOFT |
| Tick count | `state.json::tick_count` | > 50 | SOFT |
| Active dispatch fanout | `len(state.active_dispatches)` over time | rolling avg > 6 | INFO |
| Wave plan churn | commits-since-session-start | > 30 | SOFT |
| STATUS.csv growth | row count delta vs session start | > 20 rows | SOFT |
| System memory used | `psutil.virtual_memory().percent` | > 85% | MED |
| System memory used | `psutil.virtual_memory().percent` | > 95% | HIGH (crash imminent) |
| Claude process RSS | `psutil.Process().memory_info().rss` | > 2 GB | MED |
| CPU sustained load | 60-second average | > 90% | MED |
| Disk free | `psutil.disk_usage('/').percent` | < 5% free | HIGH |
| jsonl log size | `coord/dev_loop/log.jsonl` filesize | > 50 MB | SOFT |

### 2 — Recommendation logic

```python
def recommend(signals: dict) -> Recommendation:
    """Decide whether to alert the operator and how strongly.

    Returns one of:
      Recommendation.NONE         — no action
      Recommendation.SOFT         — "consider a fresh session"
      Recommendation.STRONGLY     — "recommend transfer now"
      Recommendation.CRITICAL     — "crash imminent, transfer or save state immediately"
    """
    if signals["mem_pct"] >= 95 or signals["disk_pct_free"] < 5:
        return Recommendation.CRITICAL
    soft_count = sum(1 for s in SOFT_SIGNALS if signals.get(s, False))
    if signals["mem_pct"] >= 85 or signals["claude_rss_mb"] > 2048:
        return Recommendation.STRONGLY
    if soft_count >= 3 or signals["session_age_h"] > 4:
        return Recommendation.SOFT
    return Recommendation.NONE
```

### 3 — Surfacing protocol

Mirrors the L1-L5 escalation pattern but uses a parallel "transfer"
channel so it never interferes with normal escalations:

| Recommendation | Surface | Channel |
|---|---|---|
| NONE | nothing | — |
| SOFT | one-line note appended to the dev manager's next reply | inline |
| STRONGLY | banner at the TOP of the next reply with "transfer recommended" | inline + `coord/dev_loop/handoff_recommended.md` written |
| CRITICAL | replaces normal reply with crash warning + auto-saved master prompt | inline + `coord/dev_loop/handoff_CRITICAL.md` written + Windows toast |

When STRONGLY or CRITICAL fires AND operator agrees → dev manager runs
`harness session bootstrap --reason=<short>` which produces the
master prompt + saves to `coord/session_handoff_<timestamp>.md`.

The operator pastes the contents of that file into a fresh Claude
session — the new session boots with full state.

### 4 — Master prompt structure

`harness session bootstrap` emits a single markdown file with five
ordered sections, designed for paste-into-fresh-Claude:

```
# Session handoff — 2026-05-21T05:00:00Z

## 1. Base bootstrap (durable, project-invariant)
<<< contents of coord/SESSION_BOOTSTRAP.md or CLAUDE.md verbatim >>>

## 2. Session state snapshot (frozen at handoff time)
- last commit: <sha + message>
- STATUS.csv summary: 39 shipped, 2 parked, 0 unresolved
- active dispatches: <table of in-flight task_ids + ETAs>
- recent escalations: <last 3 from state.json>
- engine cooldowns: <any>

## 3. Wave plan delta (what's changed since the original boot)
- newly shipped: <commit hashes>
- newly added rows: <STATUS.csv ids>
- now in flight: <task_ids>

## 4. Next-action queue (what the new session should do first)
<one paragraph operator-style intent: "tackle backlog X, integrate
in-flight dispatch Y, then dispatch v2/B per spec/...">

## 5. Memory pointers (so the new session loads the right context)
- All memory entries referenced by this work — list the slugs
  (the new Claude will load them from operator's memory store on
  session start)
```

### 5 — Where it lives in the codebase

```
src/harness/session/
├── __init__.py
├── signals.py       — psutil + filesystem signal collectors
├── recommender.py   — Recommendation enum + recommend() logic
├── bootstrap.py     — generate_master_prompt(reason) -> str
└── monitor.py       — check() one-shot entrypoint called from CLI

src/harness/cli.py
├── @cli.group(name="session")
│   ├── check                — print recommendation + signals JSON
│   ├── bootstrap [--reason]  — emit the master prompt to stdout (or --out path)
│   ├── ack                   — operator dismisses the current handoff_*.md flags
│   └── crisis-check          — runs check() with --strict thresholds + windows toast on HIGH/CRITICAL

tests/test_session_signals.py
tests/test_session_recommender.py
tests/test_session_bootstrap.py
tests/test_session_monitor.py
```

### 6 — Dev-manager tick integration

Add a new "Step 0.5" to `coord/dev_loop/manager.md`:

```markdown
0.5 — Session health check (after observer flag check)
   - Run `harness session check --quiet`
   - If Recommendation == SOFT: append one-line note at the end of
     the reply ("note: session has been long; transfer recommended
     when convenient — `harness session bootstrap`")
   - If STRONGLY: open the tick reply with a banner + render the
     handoff_recommended.md file
   - If CRITICAL: replace the tick reply with the crash warning;
     auto-write the master prompt to coord/session_handoff_<ts>.md;
     halt further dispatches until operator acks
```

### 7 — Resource-pressure auto-trigger

Independent of the dev-manager tick cadence, a Windows Task Scheduler
entry (`XaxiuHarnessSessionCrisisCheck`) runs every 5 minutes and
fires `harness session crisis-check`. If signals hit CRITICAL, it
writes the handoff file + raises a Windows toast notification. The
dev manager will see the file on its next tick and act on it.

This solves the "operator declined the SOFT recommendation" case the
brief calls out — even if the user said "not now", we re-alert as
soon as resource pressure mounts.

## Acceptance criteria

1. `harness session check` prints a JSON object with all signal values
   + the recommendation in <1 second.
2. `harness session bootstrap` produces a 5-section markdown file that
   parses cleanly as a Claude session-boot prompt (verified by
   round-tripping into a fresh runner).
3. Forcing `psutil.virtual_memory()` to return 96% via mock produces
   Recommendation.CRITICAL.
4. The Windows Task Scheduler `XaxiuHarnessSessionCrisisCheck` entry
   exists after `harness session arm-crisis-check`.
5. `python -m pytest tests/ -q` passes including all session-* tests.
6. Single commit per implementation packet:
   `feat(session): handoff monitor — proactive transfer recommendation`

## Non-goals (v1)

- Cross-machine handoff (e.g. mobile-to-desktop) — single-machine for v1.
- Automatic invocation of a fresh Claude session — operator must paste
  manually; we only generate the master prompt.
- Streaming-context-window measurement — Claude doesn't expose this;
  we infer from elapsed time + commit volume + system memory only.

## Reference

- `coord/SESSION_BOOTSTRAP.md` — pattern source for the durable boot section
- `src/harness/observer/scheduler.py` — pattern for Windows Task Scheduler entry
- `src/harness/observer/flags.py` — pattern for severity-tagged flag files
- `pyproject.toml` already declares `psutil` is NOT a dep — needs adding
- Memory `feedback_active_tracking_table` — mtime canary, two-line litmus

## Adds to dependencies

- `psutil>=5.9` (cross-platform resource signals; small, well-maintained)
