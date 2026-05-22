<!-- engine=deepseek model=deepseek-v4-flash success=True latency_ms=15259 chars=2664 -->

# 1. Was the inline drift mostly Claude's role-discipline gap, or also a packet/dispatcher gap?

Claude violated `feedback_plan_first_dispatch_default` by fixing defects inline, but the root cause is a dispatcher gap: the 30‑LOC ceiling and single‑stage review packets are too brittle for bug‑fixing workflows.  When a defect requires multi‑file surgery or client‑side config tuning, Claude correctly judged that shipping a “fix” packet would exceed the 30‑LOC limit or fail engine review (as happened with the 10 KB review‑packet).  The dispatcher lacks a “quick‑fix” mode that lets Claude assign small, autonomous engine tasks below the packet threshold without personal execution.  So both: discipline gap visible, but the dispatcher should have offered a legal escape hatch.

# 2. Throughput ceiling.

With perfect discipline from minute 1:  
- **Startup + spec parsing**: 30 min  
- **Each feature cycle**: plan (5 min) → dispatch 2–4 engine packets (15 min parallel) → validation + integration (10 min) → merge & test (10 min) → total ~40 min per feature.  
- **Realistic**: 6–8 features in 8 hours. Due to engine timeouts (60 s server disconnect) and chain fallback (120–240 s unnecessary retries), actual throughput is 4–5 features.  Post‑fix (timeout 600 s, bypass fallback chain), **8–10 features** if packets stay under 5 KB.

# 3. Memory + hook scoping fix.

**Pick: per‑project memory directories** (e.g., `memory/xaxiu-harness/`, `memory/warehouse/`).  
Justification: 27/51 entries are warehouse‑only; loading them pollutes every xaxiu‑harness session.  A directory per project eliminates cross‑contamination at load time without migration overhead.  Hooks (`check‑csv‑stale.sh`) must be scoped via `project_root` matching in the hook runner – simple prefix check before firing.

# 4. Packet shape evolution.

Next failure mode: **semantic splitting**.  Engines disconnect at 60 s on a 10 KB review packet because the single packet is too large for server‑side inference limits.  The packet must be further split into parallel sub‑packets (e.g., 2 KB each) with a merge step, but the dispatcher cannot coordinate dependencies across sub‑packets.  Result: split packets become a DAG, requiring a real planning graph (Claude currently flattens everything).  Also, current anchor‑windowing works for read‑set, but **packet headers** (cli.py anchor) grow unbounded with session context – next disconnect will be at 15 KB metadata overhead.

# 5. One-line top change to ship next.

**Add `dispatch_packet(..., bypass_chain=True)` so that `force_engine` returns immediately on failure instead of iterating all engines (saves 60–180 s per failed packet).**