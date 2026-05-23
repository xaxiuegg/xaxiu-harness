<!-- engine=deepseek model=deepseek-v4-flash success=True latency_ms=37285 tokens_in=10939 tokens_out=3178 -->

# Consolidated Synthesis of 20-Agent Brainstorm on xaxiu-harness Autonomous Orchestrator

## 1. CONSENSUS — What the Agents Agree On

**Reject Arch A as primary orchestrator.**  
18 of 20 agents explicitly advise *against* using Claude-via-Task-Scheduler as the main overnight loop. The most frequent reasons:  
- OAuth token expiry is invisible and unrecoverable at 2 AM (kimi-1, kimi-4, kimi-8).  
- Anthropic’s anti-recursion posture makes headless automation unsupported (kimi-2, kimi-3, kimi-7).  
- Subscription quotas can be silently exhausted by an overnight run (kimi-10, mimo-1).  

**MiMo Pro v2.5 is the preferred primary orchestrator.**  
Every agent that proposes a concrete architecture names MiMo as the default engine for spec composition and dispatch. The common justification: “verified 100% reliable for spec composition and free” appears in kimi-2, kimi-3, kimi-5, kimi-9, mimo-4, etc.

**DeepSeek v4-flash is the universal fallback for reasoning/edge cases.**  
Agents routinely position DeepSeek as a low-cost ($0.001/call) safety net for ambiguous results, output validation, or when MiMo fails (kimi-3, kimi-7, kimi-9, mimo-1, mimo-2). Typical allocation: “MiMo for composition, DeepSeek for interpretation” (mimo-6, mimo-9).

**Task Scheduler launches a Python daemon, not `claude -p`.**  
All agents that propose an automated loop use a Python script (e.g., `xaxiu-loop.py`, `orchestrator.py`, `harness_executor.py`) triggered by Windows Task Scheduler. The script itself becomes the orchestrator, calling LLM APIs via HTTP.

**Path β queue is demoted to a warm‑start cache, not a life‑support.**  
Multiple agents (kimi-1, kimi-3, kimi-5, mimo-1, mimo-9) keep the pre‑composed queue for initial/urgent tasks but allow the orchestrator to generate specs on‑the‑fly when the queue empties.

**Cost target is $0–$0.50/night.**  
Every agent presumes MiMo is free and DeepSeek usage stays under a dollar, making the system effectively zero‑marginal‑cost.

## 2. SPLIT VOTES — Where the Agents Disagree

**a) Should Claude be used at all in the autonomous loop?**  
*Strong “No” camp* (12 agents): kimi-1,2,3,4,5,7,8,9,10; mimo-2,5,7.  
> “OAuth in the keychain is a mirage… a single silent `claude -p` hang at 02:00 will kill the run with no retry” (kimi-3).

*Limited “Yes” camp* (5 agents): kimi-6, mimo-3, mimo-4, mimo-10; plus mimo-X hybrid mentions.  
> “Use Claude as a ‘chief architect’ that runs periodically, not continuously — it writes a `NEXT_ACTION.md` file that a cheaper loop executes” (mimo-4).  
> “Ship Arch A as the primary orchestrator for dynamic adaptability… worth the integration effort” (mimo-10 — the sole outlier advocating Claude as *primary*).

**b) Should orchestration logic be LLM-driven or deterministic?**  
Most assume MiMo drives both composition and next‑step decisions. But kimi-7 proposes a **deterministic Python state machine** as the core, calling DeepSeek only for a structured “meta‑prompt” when the queue is empty.  
> “Stop using an LLM as the orchestrator — use a state machine. DeepSeek emits JSON; Python acts on it” (kimi-7).

**c) Which engine should compose specs when the queue runs dry?**  
Consensus is MiMo, but kimi-5 suggests **DeepSeek-only for composition** to keep MiMo for free worker dispatch. Mimo-9 splits: “Use MiMo for composing from a strict template, not creative reasoning — embed conventions in a system prompt.”

**d) Should DeepSeek be used for reasoning fallback or also for primary interpretation?**  
Kimi agents (3,4,5) often position DeepSeek as a cognitive co‑orchestrator for result interpretation. MiMo agents (1,2,8) more often keep DeepSeek as a pure error fallback, with MiMo handling both composition and interpretation.

## 3. NOVEL IDEAS — Beyond the 7 Considered Options

1. **DeepSeek Conductor + Deterministic State Machine** (kimi-7) — Combines a rigid Python loop with DeepSeek emitting structured JSON only when the queue is empty, plus a local Ollama Qwen circuit‑breaker. Rejects LLM‑as‑orchestrator entirely.

2. **Two‑Tier Scheduler: Continuous Executor + Periodic Claude Replanner** (kimi-6) — A main Task Scheduler job runs the Python executor continuously; a second job fires `claude -p` every 3 hours to audit STATUS.csv and burst‑compose 15–20 specs into the queue. This gives Claude‑quality planning without making it the live loop.

3. **Morning Briefing via DeepSeek** (mimo-1) — After the overnight run ends, call DeepSeek to generate a one‑page summary of successes, failures, and required operator actions. Turns the black box into a structured handoff.

4. **Priority Fallback Chain with Engine List** (mimo-8) — Modify `coord run` to accept `--engine-priority mimo,deepseek,kimi` and cascade automatically. Simple but explicit.

5. **Claude as “Consulting Service” / NEXT_ACTION.md** (mimo-4) — Have a separate Task Scheduler job run `claude -p` every 90 minutes to write a recommendation file; the main loop checks for this file but can fall back to heuristics if it’s missing.

6. **Split Orchestration from LLM Calls** (mimo-9) — Keep all decision logic (which row to process, retry, routing) in deterministic Python; call MiMo only for “compose spec” and “interpret result.” Keeps control flow auditable.

7. **Heartbeat File and Health‑Check Ping** (mimo-2, kimi-5) — Write a timestamped heartbeat file each cycle; if it stops updating, the operator’s morning Claude session can spot the stall.

## 4. KIMI vs. MIMO PATTERNS

| Dimension | Kimi K2.6 agents (1–10) | MiMo Pro v2.5 agents (1–10) |
|-----------|--------------------------|------------------------------|
| **Tone** | More prescriptive, detailed implementation (file locking, windowed context, PID files) | More pragmatic, “don’t over‑engineer,” references to “already proven end‑to‑end” |
| **Rejection of Claude** | Unanimous and forceful — “Structurally, they do not want to be automated this way” | Slightly softer — 2 of 10 (mimo-3, mimo-4) propose cautious Claude‑hybrid tests |
| **Fallback strategy** | DeepSeek as cognitive co‑orchestrator for reasoning, not just error recovery | DeepSeek as pure error fallback, MiMo handles interpretation |
| **Novel components** | Local Ollama Qwen as circuit‑breaker (kimi-7), two‑tier scheduler (kimi-6) | Morning briefing (mimo-1), priority engine list (mimo-8), Python determinism split (mimo-9) |
| **State management** | Focus on atomic file writes, SQLite journal, checksums | Simpler JSON checkpoint files, heartbeat probes |
| **Cost ceiling mentioned** | $5 circuit‑breaker for DeepSeek, hard dispatch caps | “$0 most nights, maybe $0.50 in tokens” |

## 5. CONCRETE NEXT STEPS (Priority Order)

### P0 — Ship the MiMo‑Primary Python Orchestrator Daemon
**What:** Write a single Python script (`xaxiu-autorun.py`) launched by Windows Task Scheduler on a 5‑minute repetition interval. The script:
- Acquires a PID‑file lock to prevent overlap.
- Reads `coord/STATUS.csv` (last 20 rows to limit context).
- Calls MiMo Pro API with a system prompt encoding operator conventions to compose the next spec and decide target engine.
- Dispatches via `coord run --watch` with a 300‑second subprocess timeout.
- Returns output—if malformed or low‑confidence (MiMo returns a confidence field below 0.7), routes to DeepSeek for interpretation.
- Updates STATUS.csv via atomic write‑temp‑rename.
- Keeps a local SQLite journal for crash recovery.
**Why:** This is the unanimous recommendation. It eliminates queue starvation, costs $0, and is fully testable today. Reference: kimi-3, kimi-9, mimo-6.

### P1 — Add Operational Guardrails: Circuit Breaker, Heartbeat, and Fallback Chain
**What:** Implement three hardening measures inside the P0 script:
- **Circuit breaker:** If MiMo fails twice consecutively (API error or invalid output), fall back to DeepSeek for *that cycle only*. If three consecutive cycles fail entirely, write an emergency marker and exit — the operator sees it in the morning.
- **Heartbeat file:** Write a timestamp to `coord/heartbeat.txt` every cycle. If missing after 30 minutes, Task Scheduler can email a warning.
- **Priority fallback chain:** `MiMo → Kimi K2.6 → DeepSeek` for spec composition; `MiMo → DeepSeek` for result interpretation. Log each cascade.
**Why:** These are the minimal safety nets to prevent silent failures. Mentioned by kimi-5, kimi-9, mimo-2, mimo-8.

### P2 — Test and Integrate Periodic Claude “Spec Burst” (Optional Phase)
**What:** After the P0/P1 system is stable for one week, create a second Task Scheduler job that fires once at 22:00 (or on demand). It runs `claude -p` with a prompt to read STATUS.csv and batch‑compose the next 20 specs into a staging queue folder. The main loop then drains those specs overnight. If the `claude -p` call fails (OAuth expiry, etc.), the loop silently falls back to MiMo composition — zero disruption.
**Why:** This gives Claude‑quality spec planning without putting Claude on the critical path. Strongest proposal from kimi-6 and mimo-3. Low risk, high potential gain.