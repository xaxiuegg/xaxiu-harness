<!-- name=M20-RISK-PROFILE latency_ms=52637 error='' -->

## Top 5 Risks — 30-Day Window

### 1. **Engine Cascade Failure** — Score: 3/5
The quarantine flow was *silently broken* until W8-AUDIT-FOLLOWUP (`7081d93`). `EngineHealth.status` rejected `quarantined`/`recovering` writes via Pydantic, but `except Exception: continue` swallowed the error. **Probability: 40%** a similar silent-failure pattern exists in another engine path. Impact: dead engine wastes dispatch cycles, triggers cascading timeouts, burns Kimi/Claude quota on doomed retries. The `engines-heal` audit is non-deterministic (PASS-STOP-STOP) — confidence the fix itself is robust: **65%**.

### 2. **Audit Gate Unreliability** — Score: 4/5
MiMo's non-determinism is the *systemic* risk. Three rows flipped PASS↔STOP with zero code change. Two persistent STOPs (W8-STOP-HOOK, W8-AUDIT-PROMPT) may be legitimate gaps *or* auditor hallucination — the snapshot doesn't distinguish. **Probability: 80%** that at least one Wave 9 row will be incorrectly held up or incorrectly cleared by the audit gate within 30 days. Without `--avg-of-N` (queued, not shipped), every audit verdict is a coin-flip on soft criteria.

### 3. **Cost Overrun** — Score: 3/5
`--engine-fill aggressive` is the default. DeepSeek handles V-file + math + ship-critical work (the most expensive paths). `harness budget` exists but there's no evidence the operator checks it. **Probability: 35%** of hitting a rate-limit or billing surprise in 30 days, especially if Kimi slots fill and DeepSeek absorbs overflow. No circuit-breaker on per-day spend is visible.

### 4. **Operator Usability Cliff** — Score: 4/5
`preflight --skip-engines` and `today` **both timed out at 30 seconds** in the snapshot. A non-technical operator hitting timeouts on the two most important daily commands will lose trust immediately. The git-stash surprise in `preflight --fix` (`W9-PREFLIGHT-FIX-NOSTASH` queued but not shipped) could lose in-progress work silently. **Probability: 60%** the operator encounters a confusing failure within 30 days.

### 5. **Scope Creep / Wave Drift** — Score: 3/5
Five W9 candidates already queued. Persistent STOPs demand resolution. Readiness-panel rerun is pending. CRLF hook fix surfaced mid-closeout. **Probability: 50%** that Wave 9 scope doubles before the first row ships, pushing delivery out by ≥1 week.

---

## Score (0-5)

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | Core flows work; quarantine schema bug was ship-blocking and only found by accident |
| **Robustness** | 2 | Silent `except Exception: continue` pattern was load-bearing; CLI timeouts survive |
| **Operator-usability** | 2 | Two critical commands time out; git-stash surprise; `--help` is technical |
| **Test discipline** | 4 | 1576 passing + mutation gate ≥3; non-determinism is auditor-side, not harness-side |
| **Risk** | 4 | Engine cascade + audit unreliability compound; operator can't self-diagnose |

## Top Blocker
Ship `W9-AUDIT-NONDETERMINISM-AVG` (median-of-3 or avg-of-5) as the *first* Wave 9 row. Every subsequent audit verdict depends on this. Without it, the audit gate is advisory noise, not a gate.

## Verdict
**SHIP-WITH-FIXES.** The harness is functional and the W8 operator-readiness work is real progress, but the audit gate unreliability and CLI timeouts are operator-facing credibility risks that should be resolved before the next wave begins.
