<!-- name=M13-PROXY-SAFETY latency_ms=32688 error='' -->

## Score

1. **Correctness — 3/5.** The 4-key proxy + circuit breaker + auto-quarantine exists, but the EngineHealth schema bug proves auto-quarantine-on-flap was *silently non-functional* until W8. Core safety claim was broken; now fixed, but trust is earned over time.

2. **Robustness — 2/5.** The `except Exception: continue` that swallowed quarantine writes is a fundamental anti-pattern in a safety-critical proxy path. What happens when all 4 keys are rate-limited or revoked? Fail-open or fail-closed? Circuit-breaker behavior is unspecified anywhere in the snapshot.

3. **Operator-usability — 3/5.** `engines-heal` + runbook help, but no proxy-specific operator guidance is visible. When the circuit breaker trips at 2am, does the non-technical operator see "traffic routed direct — keys exhausted" or a silent degradation?

4. **Test discipline — 2/5.** Zero proxy-specific tests mentioned. No proxy module appears in the mutation kill-rate table. The 32 W8 net-new tests are unspecified. There is no evidence that key rotation, circuit-breaker trip/recovery, or quarantine-on-flap are exercised by tests at all.

5. **Risk — 4/5.** The proxy's defining feature (auto-quarantine) was demonstrably broken for an indeterminate period. 4 on-disk API keys is 4× the credential-exposure surface of direct HTTPS with one key. A proxy that can silently fail its safety mechanisms is *strictly less safe* than direct HTTPS — it adds opacity, not protection.

## Top blocker

**Produce a proxy failure-mode matrix.** For each scenario — single key revoked, all keys exhausted, circuit-breaker open, all engines quarantined, TLS handshake failure — document: (a) observable behavior, (b) fail-open vs fail-closed, (c) operator action required. This is the artifact that answers "is the proxy actually safer than direct HTTPS?" Currently there is no such document anywhere in the snapshot.

## Verdict

**SHIP-WITH-FIXES.** The proxy's quarantine mechanism works post-W8 schema fix, but with zero visible proxy tests and no failure-mode analysis, we're shipping an opaque safety layer whose failure behavior is unknown — the one thing a proxy safety reviewer cannot accept.
