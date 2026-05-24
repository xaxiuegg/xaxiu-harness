# Master audit — 40-reviewer synthesis (operator summary)

**Dispatched**: 20 MiMo + 20 Kimi personas, 181s elapsed, 40/40 OK responses
**State snapshot**: `_state_snapshot.md` (18,045 chars)
**Per-persona responses**: `M01-*.md` … `K20-*.md`
**Raw concatenated**: `SYNTHESIS.md`

---

## Verdict tally

| Verdict | Count | Personas |
|---|---|---|
| **HOLD** | 10 / 40 (25%) | K01, K05, K14, K18, M01, M03, M05, M09, M10, M15 |
| **SHIP-WITH-FIXES** | 30 / 40 (75%) | the rest |
| **SHIP-AS-IS** | 0 / 40 (0%) | — |

**Zero "ship as-is" verdicts.** Every reviewer wants at least one fix before the next horizon of work.

---

## The convergent #1 finding: live-test timeouts

**35 of 40 reviewers mentioned that `harness preflight --skip-engines` and `harness today` timed out at 30s in the state snapshot** — meaning the two commands the operator runbook tells the non-technical user to run first **hung** when the panel exercised them.

Investigation post-audit:

- When run cleanly (no other Python process): preflight `~6.8s`, today `~6.7s` — both under any reasonable budget.
- When run as one of 21 concurrent subprocesses (the panel's 20 engine.dispatch() calls + the snapshot collector): both blow past the 30s timeout.
- Root cause: preflight's `loops` + `observer` checks shell out to PowerShell (~4.5s each); under contention, those calls block long enough to exceed the budget.

The convergent finding is **correct in spirit** even though the snapshot's specific failure was load-induced: **the commands are not load-resilient, and the operator runbook is the only contract they expose**. If the operator runs preflight while the dashboard is serving and a dispatch is in flight, they may see the same hang.

---

## Convergent themes (≥10 reviewers cited each)

| Theme | Citations | What it means |
|---|---|---|
| **CLI timeouts on preflight/today** | ~35 | Two operator-facing daily commands are not load-resilient |
| **Audit non-determinism** | ~30 | 3 W8 rows flipped PASS↔STOP with no code change; gate is partly noise |
| **`except Exception: continue` swallowed schema bug** | ~25 | The silent-failure pattern that broke quarantine for weeks may exist elsewhere |
| **`preflight --fix` silent stash** | ~20 | W9-PREFLIGHT-FIX-NOSTASH already queued; multiple personas call it "data loss" |
| **Mutation canary deferred** | ~15 | Only deterministic regression signal independent of MiMo — needs to ship |
| **CRLF hook false-positive** | ~12 | W9-ONCOMMIT-HOOK-CRLF already queued |
| **No install/bootstrap docs** | ~10 | Cold-start path from `git clone` to `preflight green` is undocumented |
| **CLI verb sprawl** | ~8 | 38+ verbs vs documented 22-verb contract; K07 calls it "scaffolding tombstones" |

---

## Top 5 dissents / novel findings (cited by 1-3 personas but high-signal)

These are the things the panel surfaced that **were not already in the Wave 9 queue**:

1. **M09 / SECURITY** — Prompt injection → engine exfiltrates key material into response → logged via `retro`/`replay` before redaction. Zero redaction-integrity tests exist. **`harness env` per-key presence reporting** could leak in debug mode. Memory file integrity has no check. → New W9 candidate: **`W9-REDACTION-INTEGRITY-TEST`**.

2. **M10 / STATE-ATOMICITY** — No `os.replace` temp+rename helper for any state write outside `state/files.py`. The `EngineHealth` schema bug proved silent state corruption is real. No `kill -9` mid-write test. → New W9 candidate: **`W9-STATE-ATOMIC-WRITES`** (or extend existing `_atomic_write_json` to all hot-path writes).

3. **M11 / CONCURRENCY** — `engine_health.json` is shared mutable state across `ThreadPoolExecutor` (preflight), `asyncio` (coord), and `multiprocessing` (mutation sweeps). Zero cross-runtime synchronization. A scheduled `preflight --fix` racing a manual one is the textbook data race. → New W9 candidate: **`W9-STATE-FILE-LOCK`** (`portalocker` / `fcntl` advisory locks).

4. **M13 / PROXY-SAFETY** — Zero proxy tests in the mutation kill-rate table. No failure-mode matrix exists (single key revoked / all keys exhausted / circuit-breaker open). "Auto-quarantine on flap" was silently non-functional for an unknown duration before W8. → New W9 candidate: **`W9-PROXY-FAILURE-MATRIX`** + proxy mutation kill tests.

5. **M07 / MUTATION-COVERAGE** — Mutation tracking covers 5 of ~20+ modules. W8 shipped 32 tests without re-running the sweep. → New W9 candidate: **`W9-MUTATION-MANIFEST`** (declare every module + last-sweep SHA + auto-flag stale).

---

## Wave 9 priority stack (composite-vote)

Stack-ranked by "Top blocker" citations across all 40 personas:

| Rank | Wave 9 row | Top-blocker citations | Already queued? |
|---|---|---|---|
| 1 | **W9-AUDIT-NONDETERMINISM-AVG** (--avg-of-N audit) | 10+ | ✓ queued |
| 2 | **W9-MUTATION-CANARY** (deterministic gate) | 8+ | ✓ queued |
| 3 | **W9-PREFLIGHT-FIX-NOSTASH** (no silent data loss) | 6+ | ✓ queued |
| 4 | **W9-CLI-TIMEOUT-BUDGET** (perf-regression test + degrade gracefully) | 5+ | **new — add to queue** |
| 5 | **W9-SILENT-EXCEPTION-AUDIT** (grep `except.*continue` + harden) | 4+ | **new — add to queue** |
| 6 | **W9-STATE-ATOMIC-WRITES** (M10) | 3+ | **new — add to queue** |
| 7 | **W9-STATE-FILE-LOCK** (M11) | 2+ | **new — add to queue** |
| 8 | **W9-REDACTION-INTEGRITY-TEST** (M09) | 1 | **new — add to queue** |
| 9 | **W9-PROXY-FAILURE-MATRIX** (M13) | 1 | **new — add to queue** |
| 10 | **W9-MUTATION-MANIFEST** (M07) | 1 | **new — add to queue** |

---

## What the panel did NOT find

Worth noting where the operator-readiness work IS judged sufficient:

- **Mutation kill rates** on the 5 tracked hot modules — solid across the board (highest test-quality scores in M16's deep dive).
- **Test count growth** (1576 + 6 skip) — multiple reviewers cited the 1576 as load-bearing evidence.
- **Operator runbook content** (when read in isolation) — M19 + M16 give it 4-5/5 on usability.
- **CLI verb design** (most of them) — M02 gave 4/5 correctness; the criticism is sprawl + the verbs that hang, not the design.
- **Schema fix itself** — every reviewer who mentions `7081d93` calls it a real load-bearing fix.

The harness is engineering-grade. The gaps are at the **detection layer** (audit gate non-determinism, missing canary, silent-failure swallowing) and the **edge cases of operator-facing commands** (timeouts under load, silent stash), not in the core production logic.

---

## Honest 30-day forecast (from M20's risk profile)

| Risk | Probability | Impact |
|---|---|---|
| Audit-gate row incorrectly held/cleared | 80% | medium — slows Wave 9 cadence |
| Operator encounters confusing failure | 60% | medium — trust erosion |
| Wave 9 scope doubles before first row ships | 50% | low — wave-length grows by ~1 week |
| Silent failure in another engine path (similar to schema bug) | 40% | high — same blast radius as quarantine bug |
| Cost overrun / rate-limit billing surprise | 35% | medium — operator escalation |

---

## Recommended next-session ordering (per the panel's composite vote)

1. **`W9-AUDIT-NONDETERMINISM-AVG`** first — every subsequent audit verdict depends on this being deterministic
2. **`W9-MUTATION-CANARY`** second — deterministic regression signal independent of MiMo
3. **`W9-CLI-TIMEOUT-BUDGET`** + **`W9-PREFLIGHT-FIX-NOSTASH`** in parallel — both are operator-facing safety
4. **`W9-SILENT-EXCEPTION-AUDIT`** — grep + harden the pattern that broke quarantine
5. **Re-run readiness panel** (`W9-READINESS-PANEL-RERUN`) to measure the YES-count delta vs the W8 baseline of 0/10

The panel's strongest single recommendation: **fix the audit gate before scaling usage**. Until it's deterministic, every Wave 9 row will be 3× slower because of the audit churn.

— End of summary —
