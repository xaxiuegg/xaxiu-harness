# SPEC-ID: wave-10-plan — Operator-readiness UX (CLI-literate non-Python user)

**Authored**: 2026-05-25 from the W9 readiness panel rerun (still
0/10 YES, 9 WITH GUARDRAILS, 1 NO) + the post-W9 master audit (10
HOLD → 4 HOLD, 35 SHIP-WITH-FIXES) + the W10 operator-UX thinking
panel (8 personas, mid-W10 dispatch).

**Theme**: the W8+W9 detection-layer + state-safety + production
hygiene work landed solidly.  What remains is operator UX — the
seam between "engineering-grade tool" and "CLI-literate non-Python
user can use it without support".  Honest rating gap: 2/10 for a
ChatGPT-tier user, ~5/10 for a CLI-literate user.  W10 targets the
CLI-literate-user gap (5→6.5/10); the chat-tier gap (2→7/10) is a
multi-wave structural product change documented in the W10
operator-UX panel.

**Theme corollary**: every W10 row should reduce the *operator-
visible surface area*, not add to it.  Defaults that work + verbs
that hide complexity > more flags + more knobs.

## Phases

### Phase 1 — Exit-code surface (highest leverage; everything downstream benefits)

#### W10-PREFLIGHT-EXIT-CODE-SEMANTICS — plain-language verdict line

35/40 master-audit reviewers cited that operators read `exit 1` as
FAIL when the harness intends "warning, still ok to proceed".  Exit
codes were already split 0/1/4 internally; the gap was the operator-
facing surface — no plain-language verdict.

**Acceptance**:
- `preflight.verdict_label(exit_code)` returns `(short_label, plain_explanation)` for codes 0 / 1 / 4 + an UNKNOWN fallback.
- CLI prints `Verdict: <label>  (exit code N)` + 1-line explanation after the per-check listing in pretty format.
- JSON format suppresses the verdict line (CI consumers depend on a clean machine-readable output).
- Exit code semantics unchanged so existing CI scripts keep working.
- Tests cover translation table + CLI integration per severity + JSON-mode suppression.
- README OPERATOR_RUNBOOK has a verdict semantics table.

### Phase 2 — Single-verb daily routine (panel-converged top recommendation)

#### W10-DAILY-QUICKSTART-VERB — `harness daily` meta-command

Multiple W9 readiness panel reviewers + 3 of 8 W10 operator-UX
panel personas converged on this.  Today the operator memorizes a
4-step morning routine (`preflight` → `morning-brief` → `today` →
`observer flags`).  Replace with one verb.

**Acceptance**:
- New `harness daily` (or `harness day-start`) verb.
- Sequences: `preflight --skip-engines` → `morning-brief` → `today` → `observer flags`.
- Each phase prints a clear section heading and a one-line summary status.
- Final aggregate verdict matches the worst phase's verdict (uses the W10-PREFLIGHT-EXIT-CODE-SEMANTICS verdict_label helper).
- `--full` flag includes engine probes (slower).
- Tests cover happy-path sequencing + phase-failure short-circuit behavior + verdict aggregation.

### Phase 3 — Remediation cards

#### W10-PREFLIGHT-REMEDIATION-CARDS — surface fix hints prominently

Many preflight warnings already have a `fix:` field but it's a small
indented line under a longer message.  Surface it as a callout.

**Acceptance**:
- Each warn-severity check that has a `fix` field prints a one-line "→ Fix: `<command>`" hint directly under the warning, separated visually so the operator can scan.
- The fix string is the EXACT command the operator should run (no placeholders unless unavoidable).
- Tests verify the formatter renders the hint for warn-level + skips for ok-level.

### Phase 4 — Profile-aware defaults

#### W10-PROFILE-AWARE-DEFAULTS — persisted operator profile

`--profile non_technical` exists for some commands but isn't the
default and isn't persisted.  Add a `harness profile set <name>`
verb that writes the choice to `~/.harness/profile.json`; every
profile-aware command reads it.

**Acceptance**:
- New `harness profile set <name>` + `harness profile show` subcommands.
- Profile saved to `~/.harness/profile.json` (atomic write via W9-STATE-ATOMIC-WRITES helper).
- Commands that already take `--profile` fall back to the saved profile when the flag isn't passed.
- Tests cover read/write/missing-file/invalid-json paths.

### Phase 5 — STATUS.csv surface

#### W10-STATUS-CSV-OVERWHELM — `harness status --recent N` (default 20)

296-row STATUS.csv is impossible for a non-technical operator to
scan.  Surface the present without dropping the history.

**Acceptance**:
- `harness status` (or extension to existing) accepts `--recent N` (default 20).
- Output shows the N most recent rows ranked by Updated date desc, with the row's status, title, and 1-line summary.
- Shows a "...and X older rows in coord/STATUS.csv" footer.
- Tests cover default-20 behavior + custom N + empty CSV.

### Phase 6 — Install-time setup wizard

#### W10-ENV-VAR-WIZARD — `harness install` walks through env-var population

Today: operator must know where Windows env vars live + has no
guided path for KIMI/DEEPSEEK/MIMO API key setup.

**Acceptance**:
- `harness install` (or `harness init --wizard`) launches a TUI that:
  - Lists each required env var with its purpose.
  - Prompts the operator to either paste a value (stored via DPAPI) or skip.
  - Verifies via `harness env --probe <key>` after each entry.
- Idempotent: re-running surfaces already-populated vars + lets the operator overwrite or skip.
- Tests cover prompt flow with stubbed input/DPAPI.

#### W10-DPAPI-SEEDING-VISIBILITY — runbook explains DPAPI lifecycle

Companion to W10-ENV-VAR-WIZARD — runbook section explaining where
keys live, how to rotate them, what DPAPI is.

**Acceptance**:
- OPERATOR_RUNBOOK has a new section "Where do API keys live?" explaining DPAPI in non-Python terms.
- Section includes: how to rotate a key (overwrite via wizard), how to verify a key works, what happens if DPAPI is unreadable (L5 escalation).

### Phase 7 — Mutation-coverage expansion

#### W10-FRESH-CANARY-MODULES — populate manifest for observer/loops/dashboard

W9-MUTATION-MANIFEST has 3 warm-tier modules with `last_sweep_sha=null`.
Run the canary against each + update manifest.

**Acceptance**:
- Canary run for each of observer/cycle.py, loops/runner.py, dashboard/app.py.
- `coord/mutation_targets.yaml` updated with each module's `last_sweep_sha`, `last_sweep_date`, and observed kill-rate.
- Coverage report (`harness coverage` or equivalent) shows zero never-swept warm-tier modules.

### Phase 8 — Audit infrastructure

#### W10-MIMO-FILTER-INVESTIGATION — accept DeepSeek as primary auditor

Every W9 audit hit MiMo's content filter (~60s wait before DeepSeek
fallback).  Either rephrase the prompt to not trip the filter or
switch primary to DeepSeek.

**Acceptance**:
- Decision documented in `coord/reviews/audit-engine-choice.md`.
- Either: (a) audit prompt rephrased + verified MiMo accepts it OR (b) DeepSeek promoted to primary auditor with MiMo as fallback.
- Audit script updated accordingly + tests confirm the new primary engine is used.

#### W10-AUDIT-FOLLOWUP-COMMIT-POLICY — `--reaudit` flag for followup commits

W9 hit this twice: original commit STOPped; followup landed; the
followup's audit verdict was never captured.

**Acceptance**:
- `scripts/audit_task_with_mimo.py --reaudit <row-id>` re-runs against the most recent commit touching the row's files (or against `--commit <new-sha>` explicitly).
- The new audit report cross-references the prior STOPped audit at the bottom for diff visibility.
- Tests cover the --reaudit flag + correct latest-commit resolution.

## Wave-10 closeout

When all 10 W10 rows show `Status=shipped`:

1. Author `coord/reviews/wave-10-closeout.md`.
2. Re-run readiness panel (4th iteration); compare YES-vote delta.
3. Queue Wave 11 candidates from the operator-UX panel's `W11-*` recommendations + any new findings.
4. Run `harness session ok-to-stop`.

— End of plan —
