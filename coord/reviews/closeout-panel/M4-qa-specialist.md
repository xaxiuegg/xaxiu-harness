<!-- name=M4-qa-specialist latency_ms=16594 error='' -->

1. **Your pick on the 2 documented decision points**
**W6-A3: B.** Zero kill rate on `worker.py` and `orchestrator.py` means the tests for those modules are functionally smoke tests—they verify the code runs but not what it does. Shipping with this known debt means accepting that any regression in those two critical components will pass unnoticed. The "follow-up rows" are a deferral, not a mitigation.
**W6-C2: A.** The 17 unit tests cover the state-machine contract and failure modes. The additional integration tests (real toast, race conditions) are valuable but are test-hardening items, not correctness gaps. The alarm pipeline is verifiably functional.

2. **Options the closeout did NOT consider**
- **Delegate the mutation debt to a different engine.** The closeout treats the W7-MUTATION-* rows as a single queue. A fourth option: have the DeepSeek engine, which showed higher mutation kill rates in the A3 report, write the new behavioral tests for `worker.py` and `orchestrator.py`, using its own strengths. This could yield better tests than the system that produced the zero-rate ones.
- **Merge the W6-A3 debt with the B1 retrofit.** Requiring the EngineTransport retrofit (B1) to land *alongside* the new tests for `worker.py` ensures the new code path is tested with high-quality assertions from the start, preventing a repeat of the zero-kill-rate issue.

**I'd pick:** The merge path (A3 debt + B1 retrofit). It ties the test-quality fix to the code it needs to validate, creating a stronger feedback loop.

3. **One concrete next-session recommendation**
Start Wave 7 with **W7-MUTATION-WORKER**. Run the mutation sweep script (`scripts/run_mutation_sweep.py`) only on `src/harness/coord/worker.py` to get a precise baseline. Then, use the worker's own dispatch and budget-reporting logic as the primary specification for writing 3-5 new tests that will kill at least those specific mutations. The goal is to increase that module's mutation score from 0.0 to ≥3.0 before touching anything else.
