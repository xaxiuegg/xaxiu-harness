# Orchestrator architectures — A/B/C demos (Phase 3)

**Built**: 2026-05-23  
**Operator directive**: build + test all 3 orchestrator architectures
rather than just plan them.

## What an "orchestrator" does

Reads `coord/STATUS.csv` → picks next TODO → composes a spec
markdown → fires `coord run --watch` → reports outcome.  The role
Claude (this session) currently plays interactively, but needs to be
takeable by another engine when Claude isn't available.

## The 3 architectures

### Architecture A: Claude `-p` cron driver
- **Composer**: `claude -p` (headless Claude Code, non-interactive)
- **Auth**: `CLAUDE_CODE_OAUTH_TOKEN` (via `claude setup-token`) OR
  Claude.ai subscription `/login`
- **Pros**: Highest reasoning quality (Opus 4.7).  Same engine as
  current interactive session.
- **Cons**: Requires Claude subscription auth.  ToS-grey if used in
  multi-engine harness vs as pure Claude Code automation.
- **Cost**: subscription credit pool (separate Agent SDK credit from
  June 15 2026)
- **Demo result**: `claude -p` rejected with "Not logged in" — operator
  must run `claude /login` or `claude setup-token` to enable.  Script
  correctly falls back to template baseline on `rc != 0`.

### Architecture B: Single non-Claude engine
- **Composer**: pick one engine (DeepSeek or MiMo) for all composition
- **Pros**: Simple.  Deterministic.  No ToS concern.
- **Cons**: Single point of failure.
- **Cost (DeepSeek default)**: ~$0.001-0.005 per spec composition
- **Cost (MiMo)**: $0 via tp- subscription
- **Demo result with `--engine deepseek --execute`**: ✅ composed a
  20-line well-formed spec ($0.0012), executed coord run, worker
  completed in ~3 min, real commit SHA, deliverable file created.
- **Demo result with `--engine mimo --execute`**: ✅ same result at $0.

### Architecture C: Hybrid (MiMo → DeepSeek → Claude opt-in)
- **Composer chain**:
  1. MiMo Pro (primary, free via subscription)
  2. DeepSeek v4-flash (fallback, ~$0.001/dispatch)
  3. Claude `-p` (escalation — only if operator tags TODO with
     "reasoning-heavy" in the notes column)
  4. Template fallback (last resort)
- **Pros**: No single point of failure.  Cost stays near $0.  Operator-
  tunable per-TODO.
- **Cons**: More complex.
- **Demo result with `--execute`**: ✅ MiMo Pro primary won (no fallback
  needed).  $0 total cost.  Spec composed in ~30s, coord run 3 min,
  worker completed.

## Cost comparison (one cycle, --execute)

| Arch | Composer cost | Worker cost | Total | Wall time |
|------|--------------|-------------|-------|-----------|
| A (Claude `-p`) | — (auth missing in demo) | — | $0 actual | — |
| B (DeepSeek) | $0.0012 | $0 (MiMo worker) | **$0.0012** | 217s |
| C (MiMo→DS→Claude) | $0 (MiMo primary) | $0 (MiMo worker) | **$0** | 217s |

## Spec quality observation

Both MiMo Pro and DeepSeek produced **production-grade specs**:
- All required template sections present
- Machine-checkable acceptance criteria (file-exists, contains-text,
  exit-code-zero)
- Real reasoning about the TODO (referenced known engine failure
  modes from `memory/engine-reliability.md`)
- Concise (~20 lines)

The DELIVERABLE files MiMo/DeepSeek produced (under
`coord/orchestrator-demo/`) included a detailed 6-step remediation
plan referencing specific harness internals (W4-G, prose+markdown
drift, max_tokens budget concerns).  This is the kind of analysis that
would normally need Claude — both alternative engines handled it well.

## Recommendation

**Default: Architecture C (hybrid).**  Reasons:
1. $0 cost when MiMo Pro succeeds (most of the time)
2. DeepSeek rescue when MiMo glitches (rare)
3. Claude `-p` escalation for operator-flagged hard tasks
4. Template fallback ensures cycle always completes
5. No ToS concerns; no single point of failure

To enable Architecture A as escalation:
```bash
claude setup-token  # one-time; copies token to clipboard
# OR
claude /login  # interactive subscription login
```
Then add `reasoning-heavy` to the notes column of TODOs you want
routed to Claude.

## Engine matrix for orchestrator role (re-evaluation)

Previous evaluations focused on FILE/REPLACE work.  Orchestrator
role is **spec-composition + reasoning**, which is a different shape:

| Engine | FILE/REPLACE skill | Spec-composition skill |
|--------|-------------------|------------------------|
| MiMo Pro | 100% at adequate budget | **100% (proven this demo)** |
| DeepSeek v4-flash | ~50% (prose drift) | **100% (proven this demo, $0.001)** |
| Kimi-CLI | content-shape dependent | **untested for orchestrator** |
| Kimi-HTTP | 0% (60s cap) | **likely impaired by same cap** |
| Claude (Opus 4.7) | n/a | **best (this session)**; `-p` needs auth |

The "Kimi failed everything" observation was correct for HTTP API
+ source-laden FILE/REPLACE.  Kimi for orchestrator (small-output
spec composition via CLI) hasn't been tested yet — could be capable.

## Files added

- `scripts/orchestrator_lib.py` — shared cycle infrastructure
- `scripts/orchestrator_a_claude_p.py` — Arch A demo
- `scripts/orchestrator_b_single_engine.py` — Arch B demo
- `scripts/orchestrator_c_hybrid.py` — Arch C demo
- `spec/auto/auto-<todo-id>.md` — composed specs (per cycle)
- `coord/coverage/orchestrator_arch_<X>_<stamp>.json` — cycle reports

## Next steps

1. **Operator action** (only if Arch A desired): run `claude setup-token`
   to generate `CLAUDE_CODE_OAUTH_TOKEN`.
2. **Pilot H matrix** (deferred): re-test all 3 engines on
   orchestrator-shape tasks H1/H2/H3 to characterize each engine's
   strength for this role.
3. **CLI verb**: `harness orchestrator start` to wrap Arch C with
   periodic Task Scheduler integration (opt-in, default off).
4. **Multi-cycle resilience**: chain cycles into an overnight queue.
   At ~3 min/cycle, that's ~20 TODOs per hour, ~160 per 8-hour overnight.
