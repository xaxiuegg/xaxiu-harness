<!-- name=K01-ONBOARDING latency_ms=49538 error='' -->

## Score
1. **Correctness**: 2 — W8 shipped operator readiness, yet `preflight --skip-engines` and `today` both timeout on the live Windows box; the runbook cannot compensate for a hung binary.
2. **Robustness**: 1 — Fresh clone → run preflight → 30 s deadlock with no fallback or diagnostic. The queued silent-stash bug (W9-PREFLIGHT-FIX-NOSTASH) adds surprise data loss on recovery.
3. **Operator-usability**: 1 — A non-technical user must choose `--mode`, `--profile`, and parse 30+ verbs before validation; then step one hangs. Evidence shows ~100 % first-attempt failure rate.
4. **Test discipline**: 2 — 1 576 tests miss the Windows first-run integration hang and the CRLF hook false-positive (W9-ONCOMMIT-HOOK-CRLF).
5. **Risk**: 5 — Complete onboarding blockage for the target operator profile; a clear ship-blocker.

## Plus
6. **Top blocker**: A `harness doctor --first-run` fast-path that skips DPAPI/git-depth checks known to hang under Windows Store Python, surfaces dirty-state warnings without stashing, and confirms the CLI is responsive before any comprehensive gate runs.
7. **Verdict**: HOLD. No fresh operator can complete clone-to-first-green-preflight today without technical rescue.
