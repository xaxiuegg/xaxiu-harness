<!-- name=M1-install latency_ms=33800 error='' -->

## Rubric

**Install (3/5):** `harness install` with a first-run wizard and `harness doctor` diagnostics are strong scaffolding. However, env-var setup (`KIMI_API_KEY`, `DEEPSEEK_API_KEY`) has no visible wizard step — the operator must know *where* to set Windows environment variables, which is non-trivial without guidance. DPAPI says "read works" but the *seeding* step (writing keys into DPAPI initially) isn't shown — likely undocumented for the happy path. Exit code 1 on `preflight` due to a git warning will alarm a non-technical operator who doesn't know `1 ≠ fail`.

**Daily run (3/5):** `harness morning-brief` plus `harness coord status` is a reasonable two-command cadence, and `harness dashboard-serve` exists for visual monitoring. The `--profile non_technical` flag reduces verbosity. But the *default* flags (mode, escalation-threshold, explore-on-uncertainty) aren't obviously set once — the operator must either always pass flags or edit a config file. A `daily` or `start` verb that loads a saved profile is missing.

**Observe (4/5):** Observer primitives, heartbeat, STATUS.csv, dashboard, and `morning-brief` all target the non-technical lens directly. The 296-row STATUS.csv is readable in Excel. Engine cooldowns/reliability have dedicated verbs. Only gap: no `--watch` or live-updating view for dispatch runs.

**Recover (2/5):** `engines-heal` is a good one-command recovery. But the proxy failure matrix (W9, still `todo`) means proxy failures are opaque. `preflight` exit-code ambiguity hides real problems. No `harness fix --auto` verb that resolves common warnings (e.g., git clean) without the operator understanding git.

## 5. Hand to a non-technical operator today?

**WITH GUARDRAILS.** The CLI surface is rich and `--profile non_technical` exists, but three critical seams require hand-holding: (a) initial env-var population has no guided path, (b) DPAPI seeding is invisible in the snapshot, and (c) preflight's warning-vs-failure semantics will confuse anyone who doesn't know exit codes. A 30-minute pairing session would cover it; alone, expect 90+ minutes of floundering.

## 6. Top 3 blockers

1. **`harness install --wizard` must demo env-var setting end-to-end** — show the exact Windows Settings dialog or auto-populate from a `.env` file.
2. **`harness preflight` needs human-readable pass/fail** — replace exit code 1 for warnings with "PASS with notes"; save exit 1 for actual failures.
3. **`harness quickstart` verb** — a single command that runs `doctor` → `install` → `init` → `preflight` with progress narration in `non_technical` profile, replacing the 4-step sequence the operator must currently memorize.
