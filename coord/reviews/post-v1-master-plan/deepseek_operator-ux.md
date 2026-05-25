### Stance summary (3-5 sentences)

v1.0.0’s engine-failure-visibility layer is the right foundation, but it’s *too loud* right now: the failure summary buries real problems under 139 expected “no key” events for anthropic and gemini. I wish v1.0.0 had shipped an “engine ignore” toggle so the operator doesn’t see noise for engines they never configured. The most important property to preserve is **trustworthy failure signals** — if I can’t trust the failure summary to show only actionable items, I’ll stop reading it entirely.

### Top 3 rows to ship next (ranked)

#### 1. `W14-ENGINE-DISABLE-VERB`

- **Title**: `harness engines disable <name>` — stop dispatching to an engine without deleting its key
- **Estimated effort**: S (~2h)
- **Why this row, by YOUR lens**: The Kimi account is terminated and will keep failing on every dispatch. The operator already has a clear diagnosis (W14-KIMI-AUTH-RESTORE), but there’s no way to *tell the harness to stop trying*. Every auto-retry, every fallback to kimi generates noise, wastes retry budget, and creates confusion when `harness engines failures` shows four more “terminated” events every session. This removes a daily frustration and restores the signal-to-noise ratio of the failure dashboard.
- **Acceptance criteria**:
  - `harness engines disable kimi` removes `kimi` from the active engine pool (persisted to state file or config).
  - Disabled engines are flagged in `harness engines list` as `disabled (use 'harness engines enable <name>' to reactivate)`.
  - `harness engines --health` still probes the engine (for monitoring) but marks it `disabled` instead of `up`/`terminated`.
  - Failure summary (`harness engines failures`) excludes dispatches that were never attempted because the engine was disabled.
  - Existing `keystore` and env vars are preserved; operator can re-enable without re-entering keys.

#### 2. `W14-FAILURE-SUPPRESS-NO-KEY`

- **Title**: Auto-suppress “no key” failures from engine failure summary
- **Estimated effort**: S (~1h)
- **Why this row, by YOUR lens**: Currently `harness engines failures` credits 139 “api_error” events each for anthropic and gemini — all caused by missing keys, not transient outages. Every time the operator runs the report, they have to mentally filter “oh, that’s just the ones I never configured.” This is a high-frequency papercut that undermines confidence in the new visibility layer. Strengthens **trust**: the summary should only show failures the operator can actually act on.
- **Acceptance criteria**:
  - `harness engines failures` omits engines where `keys_present` is `false` (from capabilities snapshot) unless `--all` flag is passed.
  - The summary header includes a note like `(anthropic, gemini omitted — no API key configured. Use --all to include.)`.
  - Existing no-key events in the probe log are still recorded (for historical completeness) but excluded from aggregated counts by default.
  - No change to live probe output; `harness engines --health` still shows `no-key` status.

#### 3. `W14-KIMI-RECOVERY-GUIDE`

- **Title**: One-command guide for Kimi account termination — inline recovery path
- **Estimated effort**: XS (~0.5h)
- **Why this row, by YOUR lens**: The operator sees “kimi: terminated” and the W14-KIMI-AUTH-RESTORE row is a todo, but there is no *immediate* action they can take except reading a long diagnostic blob. The operator wants the tool to say “Here’s what to do now” without leaving the terminal. Strengthens **recoverability**: a 30-second session to decide whether to disable kimi or contact support.
- **Acceptance criteria**:
  - `harness engines --health` shows `kimi: terminated — run 'harness engines guide kimi' for recovery options`.
  - `harness engines guide kimi` prints a concise 5-line actionable menu: disable kimi, email support, replace key, switch to Kimi Platform, or drop kimi entirely.
  - The guide reads from a static Markdown file so the operator can edit it.

### Rows you’d DROP from CURRENT_PLAN.md’s Week 2/Week 3 sections

**Schema versioning** (Week 3 polish) — This is a hypothetical “first data-structure change” scenario. Today the operator sees *zero* structural-change pain. It’s a solution in search of a problem. Drops effort that should go to noise reduction.

**Hallucination test harness** (Week 3 polish) — This is a developer-quality gate, not operator friction. The operator doesn’t need to test for hallucinations; they trust the engine outputs. Move to indefinite deferred.

**(None from Week 2)** — Backup secrets redact, CI doc-doc-sync, disk prune, lock deps, and auto-default guardrails all reduce operator surprise or recovery cost, so they stay.

### Single most important action this week

**Add `harness engines disable kimi` as a one-line implementation before any other Week 2 row — this alone kills the highest-frequency noise source visible in the failure summary today.**

### Confidence in your own recommendation (0.0-1.0)

**0.85** — I am confident because the failure summary data shows concrete evidence of noise (139 no-key events each for anthropic/gemini), and the Kimi terminated state is a daily frustration. I would be less confident if the operator reports they rarely look at `harness engines failures`; but given the new visibility layer is a v1.0.0 highlight, I assume they will check it regularly.

### What this lens systematically MISSES

These recommendations prioritize operator calm over data integrity — suppressing failure counts could hide a scenario where a key was accidentally unset, and disabling an engine without purging its key could leave stale credentials in the environment. A **security/ops** reviewer should audit the engine-disable persistence and ensure failure suppression includes a clear escape hatch.