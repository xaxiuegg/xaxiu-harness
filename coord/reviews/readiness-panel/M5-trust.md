<!-- name=M5-trust latency_ms=36419 error='' -->

## Rubric

1. **Install** (2/5): Preflight fails with two blockers: dirty git state and pytest failures. Fix instructions require Python/debugging (run pytest, commit). Non-technical operator cannot resolve without assistance.

2. **Daily run** (3/5): `morning-brief` command exists, but sequence isn't obvious. Requires knowing to run preflight first, which currently fails. No clear "start my day" script.

3. **Observe** (4/5): STATUS.csv is operator-readable. Dashboard command exists. Observer commands available but not simplified for non-technical use.

4. **Recover** (2/5): Remediation paths are technical. "Run pytest, fix failures" and "rotate keys or quarantine engine" require Python/engine knowledge. No simplified recovery CLI for common issues.

5. **Hand to non-technical operator?** NO. The preflight failures block autonomous use, and recovery requires technical intervention. Without resolving git state and test failures, the operator cannot safely start the loop. The trust contract isn't established because the operator cannot verify the system is in a clean state.

6. **Top 3 blockers**:
   - **`harness fix --non-technical`** command that auto-commits stashes and runs pytest via CI, providing plain-language results.
   - **`harness loop --start`** wrapper that runs preflight, fails clearly with dashboard instructions if red, then starts with safe defaults (L5 escalation, conservative mode).
   - **`harness recover --common`** that handles dead engines (rotate keys automatically) and git state (stash changes) with non-technical explanations.
