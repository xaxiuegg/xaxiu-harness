<!-- name=K03-FAILURE-MODES latency_ms=120024 error='' -->

## Score
1. **Correctness — 3**: Spec implemented, but silent stash and 30 s Windows timeouts are operator-safety gaps.
2. **Robustness — 2**: Timeouts, CRLF hook false-positives, and historically swallowed exceptions let failures cascade.
3. **Operator-usability — 3**: Runbook exists, yet daily commands timeout and `--fix` destroys uncommitted work without warning.
4. **Test discipline — 3**: 1 576 tests cover logic, but Windows CLI timeouts and Bash hook CRLF behavior lack coverage.
5. **Risk — 4**: First-week operator faces data loss or morning blindness; blast radius is immediate productivity halt.

**Failure modes (freq×impact, sorted):**
1. **Preflight/`today` 30 s timeout** — daily blindness; retry/skip engines; 5–10 min.
2. **`preflight --fix` silent stash** — lost uncommitted changes; `git stash pop`; 5–30 min.
3. **CRLF commit-hook false-pos** — commits blocked; bypass hook; 5–15 min.
4. **Dead-engine quarantine loop** — zero dispatch; `engines-heal`; 10–20 min.
5. **MiMo audit flip** — confidence erosion; accept-as-shipped precedent; 15–45 min.
6. **Verb-tree overload** — wrong destructive command; runbook + reverse; 10–30 min.
7. **Secret/DPAPI expiry** — total outage; re-seed keys; 10–30 min.

6. **Top blocker**: Ship W9-PREFLIGHT-FIX-NOSTASH (replace auto-stash with a loud confirmation prompt).
7. **Verdict**: SHIP-WITH-FIXES — W9 queued patches are small, localized, and required for first-week operator survival.
