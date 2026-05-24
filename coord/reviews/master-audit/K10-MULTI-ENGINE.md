<!-- name=K10-MULTI-ENGINE latency_ms=42171 error='' -->

## Score

1. **Correctness — 2/5**: `--engine-fill` and `engines-cooldowns` exist but the snapshot offers no proof the scheduler actually saturates Kimi slots before fallback or that dispatch respects cooldown timestamps.
2. **Robustness — 2/5**: `preflight --skip-engines` hangs for 30 s, indicating engine-pool I/O is not isolated by the flag; the `EngineHealth` schema mismatch silently failed every quarantine until manual discovery.
3. **Operator-usability — 3/5**: `engines-heal`, `engines-cooldowns`, and `today` are operator-friendly verbs, but a hung preflight blocks the non-technical daily workflow and erodes trust.
4. **Test discipline — 2/5**: 1576 passing unit tests missed a silent schema rejection and a CLI timeout; no mutation or integration coverage pins slot-cap or cooldown-enforcement behavior.
5. **Risk — 4/5**: Unenforced slot policy wastes subscription burn; unvalidated cooldowns risk cascading 429s across Anthropic/Gemini/DeepSeek within 30 days.

**Top blocker:** A single integration test that dispatches N+1 packets with `--engine-fill aggressive` and asserts Kimi concurrency hits its slot ceiling before any fallback, plus a `<5 s` timeout-regression test for `preflight --skip-engines`.

**Verdict:** SHIP-WITH-FIXES — engine-pool CLI contracts look operator-ready, but the hanging preflight and unvalidated slot policy make multi-engine discipline ceremonial rather than enforced.
