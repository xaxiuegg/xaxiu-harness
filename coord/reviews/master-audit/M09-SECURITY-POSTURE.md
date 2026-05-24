<!-- name=M09-SECURITY-POSTURE latency_ms=31646 error='' -->

## Score

**Correctness (3/5):** DPAPI + env-wizard path is documented and functional; redaction integrity test exists (W9); but `panic-dump` secret-scrubbing is untested — no evidence of a redaction-canary that verifies output before it leaves the process.

**Robustness (2/5):** L5 DPAPI fallback path is a blind spot — what materializes when DPAPI is broken? If it falls back to plaintext env vars or an unprotected `secrets.json`, that's your leak. The `except Exception: continue` pattern discovered in the quarantine schema bug tells me the same anti-pattern likely exists near secrets.

**Operator-usability (4/5):** `harness env-wizard` + `harness env` + DPAPI section in runbook is solid for non-technical operators. Rotation flow documented. L5 fallback surfaced as "call engineering" — correct.

**Test discipline (2/5):** Redaction-integrity-test exists but no mutation kill-rate data for `redact/` or `secrets/` modules — they're not in the top-5 or even warm-tier canary. The injection scanner (W8-AUDIT-PROMPT) scores 0.25 STOP and is **not load-bearing** — it's a post-hoc review tool, not a pre-commit gate. If an engine returns a dispatch containing raw DPAPI-decrypted material, no scanner catches it before commit.

**Risk (3/5):** Modified tracked files (`git_clean` fail) could include secrets in working tree. The `git status` detector (W5-P) catches edits but not content. A `.env` or `secrets.json` staged for commit has no pre-commit content-scan.

## Top blocker

Add a **pre-commit hook that scans staged content for DPAPI-decrypted patterns** (API key regex, `secrets.json` content hashes). The redaction-integrity-test proves the *regexes* work; wire them into `git diff --cached --name-only` filtering. One concrete file: `hooks/pre-commit` calling the existing redaction patterns against staged blobs. This closes the path where secrets leak through version control — the only unmonitored egress.

## Verdict

**SHIP-WITH-FIXES.** The DPAPI layer itself is sound; the gap is the egress path — no gate between DPAPI decryption and git/logs/process-snapshot. The pre-commit redaction hook plus a `panic-dump` redaction-canary test would close it.
