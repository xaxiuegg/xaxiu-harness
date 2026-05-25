### Stance summary (3-5 sentences)

v1.0.0 shipped a solid foundation—audit trail, install verify, SDK, failure visibility. But the current plan is still organized around *maintenance and polish* (backup redact, doc sync, disk prune) instead of *compound leverage*. The one thing v1.0.0 missed is a **one-command engine bootstrap** that makes adding or replacing an engine a 10-second task instead of a 30-minute manual env-vars edit. The most important property to strengthen is **convention-over-configuration**: every engine slot should auto-discover its key, endpoint, rate limits, and health check URI from a single declarative YAML file, so future features (cost caps, fallback tiers, auto-retry) can be applied uniformly without per-engine if-else.

### Top 3 rows to ship next (ranked)

#### 1. `W14-ENGINE-AUTO-CONFIGURE`

- **Title**: One-command engine setup from env variables + `harness engines init`
- **Estimated effort**: M (3–4h)
- **Why this row, by YOUR lens**: Right now every new engine requires manual env-var setting, manual `harness env` check, manual health probe wiring, and manual fallback logic. A single `harness engines init` that scans `KIMI_API_KEY`, `DEEPSEEK_API_KEY`, etc., writes `~/.harness/engines.yaml` with defaults (endpoint, rate limit, model list, health probe URI), and validates each key live—this would let us add the **5 future engine-related features** (cost cap, auto-fallback, parallel dispatch, quota pre-check, engine-specific auto-defaults) at half the cost because they’ll read from a single config object instead of scattered env-var conditionals.
- **Acceptance criteria:**
  - `harness engines init` scans all `*_API_KEY` env vars, creates `~/.harness/engines.yaml` if it doesn’t exist.
  - Each engine entry includes `endpoint` (inferred from convention), `models` list (discovered or default), `health_probe_uri` (defaulted to `/v1/models` or similar), `rate_limit` (default 10/s).
  - `harness engines validate` runs a live probe on each configured engine and prints a table: name, status, key_present, endpoint_reachable.
  - All existing engine code (`transport.py`, `cli.py`, `probe_engine_live`) reads from the YAML when present, with env-var override fallback.
  - 15+ tests: init (dry-run, overwrite rejection), validate (live, offline, partial), fallback to env-vars, backwards compatibility with current env-var-only setup.

#### 2. `W14-PANEL-CODE-GEN`

- **Title**: Generate panel-fire scripts from a 10-line YAML spec
- **Estimated effort**: M (3–5h)
- **Why this row, by YOUR lens**: Every strategic panel (v1-release-gate, audit, operations) requires hand-writing a Python script with engine dispatch, retry logic, verdict parsing, output formatting. That’s wasted friction that discourages running panels frequently. A `harness panel generate "release-check" --engines deepseek,mimo` that produces a ready-to-run `scripts/release_check_panel.py` with *all* the boilerplate (source pack assembly, retry, verdict voting, output to `coord/reviews/`) would let us run 3x more panels per sprint, catching regressions earlier and shipping with higher confidence. It’s a classic template multiplier.
- **Acceptance criteria:**
  - `harness panel list` shows available templates (`release-gate`, `audit-task`, `burn-in`).
  - `harness panel generate release-gate --engines deepseek,mimo --output scripts/my_check.py` creates a valid Python file that, when run, reads the current `CURRENT_PLAN.md` + `STATUS.csv` as source pack, fires the selected engines, writes per-engine verdicts + a `FINAL_VERDICT.md`, and returns exit code 0/1.
  - Generated script uses the same retry/fallback patterns as the existing `v1_release_gate_panel.py` (no regressions).
  - The template is parameterized: `--source-pack-cmd` to specify how to build the source pack (default: `harness plan show --format json + cat STATUS.csv`).
  - Tests: generated script runs end-to-end with mocked engines (mock adapter), produces correct output structure, handles engine failure gracefully.

#### 3. `W14-DEFAULT-DRIFT-GATE`

- **Title**: Auto-trigger drift tests for every default value in the codebase
- **Estimated effort**: S (2–3h)
- **Why this row, by YOUR lens**: The current plan has a 4–5h row “Auto-default guardrail CI framework” which is a one-off per default. Instead, write a **generic** `pytest` fixture that scans all defaults (max_tokens, timeout, fallback order, retry count, etc.) via a convention: every default constant in `harness/constants.py` or decorated with `@default`. Then the fixture generates a drift test for each: “if this default changed, which test would fail?”. This makes future default changes **safe by construction**—you can shift a default in 1 line without worrying about silent behavior changes. It unblocks us to rapidly iterate on defaults (e.g., reduce default timeout, increase retry) because we’ll see the blast radius instantly.
- **Acceptance criteria:**
  - A module `tests/drift/test_defaults_invariants.py` with a single test function that uses introspection to find all `Default` instances in `src/harness/constants.py` (or any file that exports a `Default` namedtuple) and for each, runs a small “what if I changed this to X” simulation that asserts the existing behavior still makes sense (e.g., max_tokens <= 32768, fallback order contains only configured engines).
  - The test runs in <5 seconds (no actual engine dispatch).
  - Any new `Default` registered without a corresponding drift test causes CI to fail.
  - Existing codebase has 5+ drift tests already (for the Tier 1 Shifts A+F, for example).
  - Documentation in `CLAUDE.md` explaining the convention for adding a new default.

### Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

- **CI doc-doc-sync gate** (Week 2, S, 1h) — **Drop**. This is a manual gate that relies on humans reading docs; the real cost is *content drift*, not missing cross-references. A 1h improvement that saves 1h of manual review once is negative leverage. Better to invest that hour into a `harness docs lint` that auto-generates cross-references from the SDK spec.
- **W13-DISK-PRUNE** (Week 2, S, ~2h) — **Drop**. Disk hygiene is maintenance, not leverage. The audit ledger already has a 7-day TTL. If disk pressure becomes a real problem (e.g., >1GB), then ship a one-liner. Until then, it’s busywork.
- **W13-LOCK-DEPS** (Week 2, S, ~2h) — **Drop**. Dep-pinning is good practice but doesn’t unlock future features. The current pinning (`pip install -e .` with `--quiet`) is already reproducible per commit. Lock file adds a maintenance burden for solo operator with no multi-platform builds.
- **All Week 3 rows** (schema versioning, `--did-you-mean`, hallucination test harness, Tier 2 shifts) — **Drop**. These are optional polish that don’t compound. Schema versioning only matters on first data-structure change; `--did-you-mean` is cute but low ROI; hallucination test harness is research-grade; Tier 2 shifts are incremental. None unblocks 5 future things.

### Single most important action this week

Ship `harness engines init` so that every future engine-related feature (cost caps, fallback, parallel dispatch) reads from one declarative config instead of scattering env-var checks across 15 files.

### Confidence in your own recommendation (0.0-1.0)

**0.82** — Confidence is high that engine config unification is a force multiplier, but it depends on the operator’s willingness to adopt a new config file over env vars. Lower confidence if the operator prefers direct env-variable control for auditability; higher if we add `harness engines show --yaml` and `--validate` to keep visibility.

### What this lens systematically MISSES

Velocity underweights **security and recoverability**: dropping backup-redact and integrity verification could lead to a data loss incident that halts all forward progress. The Safety and Operations lenses should weigh whether to keep those as a precondition before the accelerate rows land.