<!-- name=M5-architect latency_ms=15742 error='' -->

### 1. Your pick on the 2 documented decision points

**W6-A3 (mutation sweep)**: Option B. The mutation sweep revealed that 3/5 modules have test suites that don't verify real behavior—they are testing scaffolding, not logic. Closing Wave 6 without fixing this foundational test debt means all future work rests on a floor that may not hold. The "report + follow-up" option is just moving the debt.

**W6-C2 (dead-engine alarm)**: Option A. The alarm's core state machine and dispatch logic are validated by 17 unit tests that cover the intended cycle. The requested behavioral integrations are test-quality improvements, not implementation flaws. The alarm works; ship it and refine tests later.

### 2. Options the closeout did NOT consider

**Option C: Partial scope for A3**—require the test-hardening work only for `worker.py` (zero kill rate) before closing Wave 6, as it's the core coord logic. Defer `concrete.py` and `orchestrator.py` to Wave 7. This focuses debt reduction where it matters most.

**Option D: Dependency-ordered close**—first complete the B1 retrofit (EngineTransport), *then* apply the mutation sweep to the refactored code. Retrofitting may change the module boundaries and test surfaces, making current mutation results obsolete. This would mean a brief "Wave 6.5" extension.

If allowed, I'd pick **Option D**. It avoids measuring and hardening tests on a code shape that's about to change, which is a classic structural waste.

### 3. One concrete next-session recommendation

If opening Wave 7, start with **fixing the `worker.py` budget hook** (`input_tokens=0`). It’s a 1-line bug that silently corrupts cost/observability data for all `swarm/*` dispatched runs. Fixing it is quick, restores data integrity for all future work, and is a prerequisite for trusting any budget-related analysis in later waves.
