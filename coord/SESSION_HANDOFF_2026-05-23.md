# Session handoff — xaxiu-harness Wave 6 (2026-05-23)

> **Paste this entire file as the first message in a fresh Claude Code
> session to resume Wave 6 work.** It is self-contained — the new
> session has no memory of the prior conversation.

You are resuming a Claude Code session on the xaxiu-harness project.

- **Repo**: `D:\xaxiu-harness-standalone` (Windows, Python 3.13)
- **GitHub**: `xaxiuegg/xaxiu-harness`
- **Date pinned**: 2026-05-23
- **Mode**: AUTONOMOUS LOOP — see "Autonomous loop expectations" below

---

## Operator standing directives (verbatim — do NOT deviate)

1. **"Full dev manager authority. Commit/push/dispatch/install
   without per-action confirmation. Only escalate L5 errors. No
   permission-seeking on tactical decisions."**
2. **"No Anthropic API key — ever. Only Kimi / MiMo / DeepSeek keys.
   Claude itself is usable via OAuth subscription only (no console
   API). Claude is now an engine peer, not an orchestrator."**
3. **"For each Wave 6 task: run a MiMo audit. ≥0.7 confidence = PASS,
   <0.7 = STOP for operator review. Consult as many MiMo agents
   as needed, but DO NOT fall for Goodhart — don't shape audit
   prompts to be flattering. Use MiMo for genuine quality checks."**
4. **"Don't ship features faster than you validate them."**
   (Skeptical Engineer reviewer, 5-MiMo session review, 2026-05-23)
5. **"Prefer larger working surface — don't trim for safety."**
6. **"Autonomous sessions run until wave_plan empty, not until task
   done."** (memory: `feedback_full_automation_until_wave_plan_empty`)

---

## Autonomous loop expectations

This session is **autonomous** — operator may or may not be at the
keyboard. You drive the loop until:

- All Wave 6 tasks (A1, A2, A3, B1, B2, B3, C1, C2, CLOSEOUT) pass
  their MiMo audit gate, OR
- An L5 error surfaces and operator review is genuinely required
  (use `handle_harness_error` + the W5-PP toast notification), OR
- `harness session ok-to-stop --json` returns `ok_to_stop=true` with
  recommendation ≥ STRONGLY.

**Self-pacing**: when waiting on a bg dispatch (5–15 min is normal):
- Use `run_in_background: true` on the Bash call → you get notified
  on completion. Don't poll.
- For external state polling (CI run, Task Scheduler tick) use
  `ScheduleWakeup` with `delaySeconds=1200–1800` (long fallback).
- The `/loop` slash command is available for genuinely cron-style
  recurring work — but Wave 6 is sequential, so it's not needed.

**Between tasks**: run `harness session ok-to-stop --json` to check
the stop-gate. If `ok_to_stop=false`, keep dispatching. Memory rule:
"STATUS.csv should never be empty" — and 8+ queued production rows
are still there.

**Never silent-loop**: if a hook fires repeatedly with no operator
text after 2 fires, EITHER execute the pending directive OR state
"halting until real input" plainly. Don't reply with single-char `.`
acknowledgements (memory: `feedback_never_silent_on_hook_loops`).

---

## What is Wave 6

The prior session shipped 23 commits across Wave 5 features. A
**5-MiMo reviewer panel** (skeptical / operator / architect / PM / QA)
gave it **0.40 avg confidence** with 5 unanimous directives:

| Reviewer | Directive |
|---|---|
| PM + Skeptical | ONE green env-doctor run before any new features |
| Operator Advocate | Ship `harness preflight` verb as readiness gate |
| Architect | Extract `EngineTransport` base class (SSE consolidation) |
| QA | Mutation-test sweep on top-5 modules |
| Operator Advocate | Ship dispatch-layer dead-engine alarm |

**Wave 6 plan** at `spec/wave-6-plan.md` sequences these into 3
phases with a MiMo audit gate between every task:

- **Phase A — Validate**: A1 env-doctor e2e, A2 token tracking,
  A3 mutation sweep
- **Phase B — Refactor**: B1 EngineTransport, B2 preflight verb,
  B3 wire preflight as autonomous gate
- **Phase C — Hygiene**: C1 cross-project hook scope, C2 dead-engine
  alarm
- **W6-CLOSEOUT**: write `coord/reviews/wave-6-closeout.md`, STOP

---

## Wave 6 progress (current state)

| Task | Status | Audit | Commits |
|---|---|---|---|
| W6-PLAN | SHIPPED | n/a | `b777fd6` |
| W6-A1-2 (fallback observability) | SHIPPED | PASS 0.85 | `5ceb8f2`, `b4577cb` |
| W6-A1-1 (D5 investigation) | SHIPPED | PASS 0.75 | `52062fa`, `e6a215c`, `f57cde7` |
| **W6-A1 main (3-engine e2e)** | **IN FLIGHT** | n/a | bg task `bs4zgxl4h` |
| W6-A2 | queued | — | — |
| W6-A3 | queued | — | — |
| W6-B1 / B2 / B3 | queued | — | — |
| W6-C1 / C2 | queued | — | — |
| W6-CLOSEOUT | queued | — | — |

**W7-SPEC-DRIFT row queued** — discovered issue: multi-worker plans
suffer spec-interpretation drift between independent agents. **Out
of scope for Wave 6.**

---

## Audit gate protocol (W6-PLAN)

After every Wave 6 task lands a commit, run:

```powershell
python scripts/audit_task_with_mimo.py <task-id>
```

Mechanics:
- Reads task acceptance criteria from `spec/wave-6-plan.md` by
  task-id (`A1-1`, `A1-2`, `A2`, …)
- Sends commit SHA + diff (16K cap) + current file contents
  (4 files × 3KB) to one MiMo Pro v2.5 agent
- Falls back to DeepSeek if MiMo gateway times out (60s)
- Writes `coord/reviews/audits/<stamp>_<task-id>_audit.md`
- **Gate**: confidence ≥ 0.7 = PROCEED. < 0.7 = STOP, fix the gaps
  the auditor identified, re-commit, re-audit. Do NOT lower the gate.

Goodhart-trap avoidance:
- Do NOT re-word audit prompts to be flattering
- Do NOT keep retrying the same prompt with the same agent hoping
  for higher confidence
- DO use multiple MiMo personas (skeptical/qa/operator) in parallel
  for diagnostic angles when stuck
- DO fix root causes the auditor identifies, not surface symptoms

---

## Engine reliability matrix (verified 2026-05-23)

| Engine | Path | $/dispatch | Reliability | Notes |
|---|---|---|---|---|
| MiMo Pro v2.5 | tp- subscription | $0 | 2/3 source-laden | 60s gateway timeout on >20KB packets — fallback rescues |
| Kimi K2.6 API | tp- subscription | $0 | **3/3 post-W5-V** | Was 0/10 historical; W5-V fixed stream=true + non-standard SSE + missing `import json` |
| DeepSeek v4-flash | sk- pay-per-token | ~$0.001 | 3/3 | Streams (W5-MM, 4× faster) |
| Claude OAuth | `claude -p` subprocess | $0 (subscription) | n/a | BLOCKED inside Claude Code session (anti-recursion). Task Scheduler bypasses via `harness orchestrator install-claude-scheduler`. |

---

## Critical known patterns (avoid these traps)

1. **Don't claim test-count without running full `pytest -q`**.
   I claimed "1424 green" twice when only filtered tests ran —
   broken STATUS.csv rows went undetected for 2 commits.
2. **STATUS.csv ID regex** `^[A-Z0-9][A-Z0-9_/-]*$` does NOT allow
   periods. Use `W6-A1-1`, not `W6-A1.1`.
3. **STATUS.csv status enum** (use these only): `shipped`,
   `in_progress`, `queued`, `todo`, `blocked`, `deferred`,
   `partial`, `proposed`, `parked`, `spec-done`, `design-done`,
   `planned`. "investigated" / "checked" / "verified" are NOT
   valid — use `shipped` when investigation IS the deliverable.
4. **MiMo intermittent 60s timeout** on audit prompts >20KB. The
   audit script's DeepSeek fallback rescues. If both fail, exit 2.
5. **W4-A silent_no_op guard** is doing its job — caught run 1 + 2
   of W6-A1 where MiMo produced 0 parseable FILE/REPLACE on Python.
   Do NOT disable it.
6. **Anti-recursion**: never spawn `claude -p` from inside this
   session. Use Task Scheduler via `harness orchestrator
   install-claude-scheduler` (W5-OO).

---

## Immediate next actions

### 1. Check the in-flight W6-A1 main run

```powershell
# bg task ID is bs4zgxl4h
Get-Content "C:\Users\xaxiu\AppData\Local\Temp\claude\D--Projects\5edcc857-3ec7-47cc-b834-752b1ab2dfe8\tasks\bs4zgxl4h.output"
```

If completed, the latest run dir is the highest timestamp under
`runs/`. Inspect:

```powershell
$rid = (Get-ChildItem runs | Sort-Object Name -Descending | Select-Object -First 1).Name
Get-Content "runs/$rid/checkpoints/worker-1.json"
Get-Content "runs/$rid/checkpoints/worker-1.progress.jsonl"
```

### 2. Interpret outcome

- **`tests_passed=True`** → W6-A1 main run **1/3 GREEN**. Stage
  + run with `--engine swarm/kimi-api` (run 2/3), then
  `--engine swarm/deepseek` (run 3/3). Each: copy from
  `spec/samples/env-doctor-check.md` to `spec/auto/`, queue
  execute with `--planner-engine kimi-api --no-merge`.
- **`tests_passed=False`** BUT `fallback_attempted` event present
  in progress.jsonl → engine produced 0 FILE/REPLACE; fallback
  ran but also failed. Document, decide whether to retry with
  different primary OR escalate as a real engine-quality gap.
- **`tests_passed=False`** AND no `fallback_attempted` event →
  fallback path broken; that's deeper than expected, investigate
  worker.py:767-815.

### 3. After A1 main ships 3/3, mark W6-A1 main = shipped in
STATUS.csv, then proceed to W6-A2 (token tracking real-API
validation). See `spec/wave-6-plan.md` §A2 for acceptance criteria.

### 4. Loop: ship → MiMo audit → if PASS, next task. If <0.7,
fix gaps + re-commit. Continue until W6-CLOSEOUT writes the
closeout report.

---

## File map (where things live)

```
spec/wave-6-plan.md                  ← the plan (read first)
spec/samples/env-doctor-check.md     ← canonical A1 spec
scripts/audit_task_with_mimo.py      ← MiMo audit gate (W6-PLAN)
scripts/verify_d5_worktree_branching.py  ← D5 evidence reproducer
src/harness/coord/worker.py          ← line 767-815: fallback chain
                                       + W6-A1-2 progress events
src/harness/engines/concrete.py      ← Kimi/MiMo/DeepSeek (max_tokens:
                                       200K/131K/32K hardware defaults)
src/harness/cli.py                   ← `start` (W5-SS), `queue execute`
                                       (W5-U), `morning-brief` (W5-RR),
                                       `spec-init` (W5-KK+W5-QQ),
                                       `orchestrator install-...` (W5-Z,
                                       W5-OO)
coord/STATUS.csv                     ← task tracker — STRICT schema
                                       (regex + status enum above)
coord/reviews/external/              ← 5-MiMo session review (READ
                                       BEFORE doing anything new)
coord/reviews/audits/                ← Wave 6 MiMo audit reports
memory/engine-reliability.md         ← live engine matrix
spec/auto/                           ← spec queue (P0-/P1- prefix
                                       priority per W5-NN)
runs/<run-id>/checkpoints/           ← per-worker state +
                                       progress.jsonl
.harness/worktrees/<run-id>/<worker>/ ← isolated git worktrees
```

---

## How to verify you're current

```powershell
cd D:\xaxiu-harness-standalone
git log --oneline -5
# Should start with f57cde7 or later

PYTHONPATH=src python -X utf8 -m pytest -q --tb=no | Select-Object -Last 3
# Should show "1424 passed" or higher; lower means something regressed

PYTHONPATH=src python -X utf8 -m harness session ok-to-stop --json
# Should show ok_to_stop=false (8+ Wave 6 rows still queued)
```

If all three look right, you have the same starting state I had.
Then proceed with "Immediate next actions" item 1.

---

## Constraints you MUST respect (anti-scope-creep guard)

The 5-MiMo review flagged scope creep as the #1 failure mode of
the prior session. Wave 6 is explicitly the corrective. Therefore:

- **Do NOT add features** unless they ship within an existing Wave 6
  task. No new CLI verbs / modules / sample specs.
- **Do NOT update** README.md / memory/ / unrelated docs until
  W6-CLOSEOUT.
- **Do NOT skip** the audit gate. <0.7 = STOP, investigate, fix
  what the auditor flagged.
- **Do NOT trust** "X is shipped" claims without empirical proof.
  D5 was claimed shipped 5+ commits ago; this session verified it
  empirically — but only after investigation. Apply the same rigor.
- **Do NOT auto-update** other projects' STATUS.csv (warehouse hook
  noise — fix is W6-C1).
- **DO run** full `pytest -q` before each commit. Filtered runs
  miss schema regressions.
- **DO use** multiple MiMo agents in parallel for diagnostic angles
  when stuck. Avoid Goodhart-shaped prompts.
- **DO use** `run_in_background: true` + Bash for long dispatches
  (~5–15 min is normal for queue execute). You get notified.

---

## What "done" looks like

W6-CLOSEOUT writes `coord/reviews/wave-6-closeout.md` containing:

- Summary: 9 tasks shipped (A1, A1-1, A1-2, A2, A3, B1, B2, B3, C1,
  C2) with their MiMo audit confidences
- A1 evidence: 3 green coord runs, one per engine
- A2 evidence: `harness budget summary` showing non-zero tokens
- A3 evidence: mutation sweep table per module
- W7 backlog: drift / engine-quality / etc. findings deferred

Then mark `W6-CLOSEOUT` shipped, push, and **stop**. Wait for
operator review before opening Wave 7.

---

_Authored 2026-05-23 by Claude (the prior session) for paste-into-new-session handoff. If you find this doc stale or misleading, prefer the live state of `spec/wave-6-plan.md` + `coord/STATUS.csv` + recent `git log`._
