# SPEC-ID: wave-11-plan — Agent-first pivot (operator-agent context preservation + cost offload)

**Authored**: 2026-05-25 from the operator's explicit commitment to pivot W11 toward agentic coding agents as the primary target user.  Synthesis of 4 panels (agent-as-user, context-preservation, w11-planning, plus the earlier chat-tier roadmap panel) and the operator's selection of recommended defaults across the 4 open questions.

**Theme**: The harness's natural user is an agentic coding agent (Claude Code, ChatGPT with code interpreter, Cursor, Aider) cloning the repo onto a fresh project and using it as a productivity multiplier — not a non-technical chat-tier human.  Wave 11 ships the SDK, secrets model, and context-preservation primitives that make "clone + use in 4 tool calls" real.

**Operator decisions locked in (2026-05-25)**:
- `COST_MAX_PER_SESSION` defaults to $5.00 or 1000 dispatches (whichever first); `budget_status()` warns at 80%
- `harness agent init --target <path>` refuses self-target by default; `--allow-self` opt-in; STATUS.csv collision → exit-3
- Dispatch cache stores FULL content; `.full()` lazy-reads from cache (no re-summarize cost)
- `adapter.py` is a single file (not a package) with documented upgrade path

## Phases

### Pre-flight (parallel; no chain deps; establishes test baseline)

#### W11-AUDIT-ALL-W10-ROWS — backfill avg-of-3 audits on every W10 commit

**Acceptance**:
- Each of the 10 W10 rows (PREFLIGHT-EXIT-CODE-SEMANTICS through FRESH-CANARY-MODULES + CLOSEOUT) audited at its commit SHA with `--avg-of-N 3`
- Reports written to `coord/reviews/audits/` with `_audit_avg3.md` suffix
- Roll-up table appended to `coord/reviews/wave-10-closeout.md` showing mean confidence per row
- Any persistent-STOP rows (mean < 0.7 across 3 runs) flagged as W11 followup candidates

#### W11-MUTATION-PATTERN-EXPANSION — async/await + decorator patterns

**Acceptance**:
- `coord/mutation_targets.yaml` `sweep_template` extended with at least 3 new patterns: `await_call_strip` (remove `await` keyword), `async_to_sync_def` (replace `async def` with `def`), `decorator_strip` (remove first decorator above function)
- Re-running `scripts/run_mutation_canary.py` against `observer/cycle.py` produces ≥1 applied mutation (was 0/3 in W10-FRESH-CANARY-MODULES)
- Existing 5 mutation patterns still work; no regression in proxy/circuit canary
- Tests for new patterns added to `tests/test_mutation_canary.py`

#### W11-HIDE-ADVANCED-VERBS — engineering verbs under `harness advanced <verb>`

**Acceptance**:
- New `harness advanced` click group hosts `coord`, `proxy`, `engines-cooldowns`, `engines-reliability`, `lint-spec`, `spec-init`, `spec-register`, `spec-verify`, `swarm-verify`, `replay`, `panic-dump`, `lock`, `burst` (operator-engineering verbs)
- `harness --help` default output shows ≤10 daily-use verbs: `ask` (if shipped), `daily`, `today`, `morning-brief`, `status`, `dispatch`, `preflight`, `env`, `env-wizard`, `profile`, `agent`, `help`
- `harness advanced --help` lists the moved verbs
- Backwards-compat: old invocations still work via deprecation alias for 1 wave
- Tests in `tests/test_cli.py` cover the namespace + alias

#### W11-ADAPTER-VALIDATE-JSON — machine-readable validation errors

**Acceptance**:
- `harness adapter validate <path> --json` emits a JSON array of error objects: `{field, line, severity ("error"|"warning"), message, suggested_fix}`
- Valid adapter returns `{"errors": [], "status": "ok"}`
- Exit code 0 for valid, 1 for any error
- Existing pretty output preserved when `--json` not passed
- Tests: valid adapter, missing-required-field, malformed-YAML; assert JSON parseable + correct schema

### Wave 11-A — Agent entry

#### W11-AGENT-INIT-VERB — `harness agent init --target <path>` one-shot bootstrap

**Acceptance**:
- New `harness agent init --target <path> [--project-type python|node|generic] [--adapter-name <name>] [--dry-run] [--allow-self]` CLI verb
- Creates the following at target (idempotent re-run = skip-or-prompt; never silent-overwrites):
  - `.env` (template with `HARNESS_KIMI_API_KEY=`, `HARNESS_DEEPSEEK_API_KEY=`, `HARNESS_MIMO_API_KEY=`, optional DPAPI commented hint)
  - `.gitignore` (only if absent; ignores `.env`, `.harness/`, `__pycache__`)
  - `adapter.py` (single file; PascalCase class name from target basename; documented upgrade path to package)
  - `CLAUDE.md` (appended `<!-- harness:agent-init -->` section if file exists; created with template otherwise; ≤800 chars total of new content)
  - `.harness/config.json` (project metadata; ISO-8601 created_at)
  - `.harness/STATUS.csv` (header row only; project-scoped, distinct from harness's own)
  - `.harness/dispatched/.gitkeep` (empty cache dir)
- Refuses self-target by default (exit 2 if `--target` resolves to harness repo); `--allow-self` opt-in
- Existing `.harness/STATUS.csv` with rows → exit 3 (data file; require manual merge)
- `--dry-run` prints all paths + contents to stdout; touches nothing; exit 0
- Prints next-command teaching block: dispatch / retrieve / budget invocations
- Tests cover: creation, idempotency, self-refuse, dry-run, STATUS-collision, project-type variants, CLAUDE.md append marker

#### W11-DPAPI-CROSS-PLATFORM — `.env`-first secrets

**Acceptance**:
- `resolve_keys()` reads `.env` first (via `python-dotenv` or hand-rolled parser), then DPAPI fallback on Windows when `--encrypt-with-dpapi` was used
- `harness env-wizard --target <path>` writes `.env` entries by default; existing DPAPI path opt-in via `--encrypt-with-dpapi` flag
- Works on Linux/Mac without DPAPI (currently breaks)
- Precedence: explicit env-var > `.env` file > DPAPI (Windows only)
- Tests: `.env` reading happy path, malformed line skipped, missing key raises typed error, Windows DPAPI fallback still works, non-Windows path doesn't touch DPAPI

### Wave 11-A.5 — SDK contract bridge

#### W11-PYTHON-SDK-API-STUBS — empty importable contract + type stubs

**Acceptance**:
- `from harness import dispatch, retrieve, budget_status, DispatchResult` succeeds
- Each function has a complete type signature; body raises `NotImplementedError("W11-PYTHON-SDK-API-IMPL pending")` so callers see the gap immediately
- `harness/__init__.pyi` provides type stubs for IDE/agent auto-complete
- `mypy --strict src/harness/__init__.py` passes (or scoped to public API surface)
- Tests: import succeeds in subprocess (no circular imports), signatures match expected shape

### Wave 11-B — Context preservation + cache

#### W11-CONTEXT-FRUGAL-RETURN-SCHEMA — DispatchResult schema + feature flag

**Acceptance**:
- `DispatchResult` gains fields: `summary: str` (≤300 chars; head+tail concat from response), `truncated: bool`, `error_excerpt: str | None`, `content_ref: str | None`
- Environment-flag `HARNESS_DISPATCH_FULL_BY_DEFAULT=True` preserves old behavior — `.text` still populated
- New summary computed via rule-based extraction: first 5 lines + last 5 lines + total-char marker; no engine call
- All existing dispatch tests pass under the feature flag
- Tests: new fields populated; flag=True preserves `.text`; flag=False returns empty `.text` + populated summary

#### W11-DISPATCH-CACHE — content-hash + adapter-hash keyed cache

**Acceptance**:
- `.harness/dispatched/<content_hash>__<adapter_hash>.json` stores full dispatch result + metadata
- Subsequent `dispatch()` with same hash returns cached result without engine call
- Cache TTL configurable (default 24h via `HARNESS_DISPATCH_CACHE_TTL_SEC`)
- `--no-cache` flag bypasses
- Adapter file edits invalidate cache (adapter_hash changes)
- Tests: same-prompt-cached, different-prompt-miss, adapter-edit-invalidates, TTL expiry, JSON-on-disk valid

#### W11-CONTEXT-FRUGAL-RETURN-LAZY — `.full()` lazy fetch + flip default

**Acceptance**:
- `DispatchResult.full() -> str` reads full text from `content_ref` (which is a path under `.harness/dispatched/`)
- After lazy-fetch path proven by tests, flip `HARNESS_DISPATCH_FULL_BY_DEFAULT` default from True → False
- Existing dispatch callers update to opt-in via `with_full_text=True` kwarg OR via the env flag
- Tests: `.full()` returns identical text to old `.text`; second call hits cache not network; environment flag toggle works

#### W11-RETRIEVE-API — `harness.retrieve(dispatch_id, scope=...)` for on-demand

**Acceptance**:
- `harness.retrieve(dispatch_id: str, scope: Literal["full", "summary", "chunks"] = "summary") -> str | list[str]`
- `scope="full"` returns identical content to `DispatchResult.full()` when called on the matching id
- `scope="summary"` returns the stored summary (~300 chars)
- `scope="chunks"` returns a list of N-token segments (default N=2000) for RAG-style retrieval
- Missing id raises `ResultNotFoundError`; corrupted file raises `ResultCorruptedError`
- Tests: each scope, missing-id, corrupted-file, latency<5ms for summary scope

### Wave 11-C — Telemetry + cross-platform

#### W11-AGENT-TELEMETRY — `budget_status()` returns offload-aware dict

**Acceptance**:
- `harness.budget_status() -> dict` returns `{session_tokens_total, session_cost_total, offload_ratio, remaining_budget_usd, dispatches_fired, engines_used: dict[str, int], avg_cost_per_token, cost_max_per_session_usd}`
- `offload_ratio` = (harness-engine tokens) / (total tokens including a synthetic operator-side estimate of ~5k tokens/dispatch — documented assumption)
- `remaining_budget_usd` reflects `COST_MAX_PER_SESSION` minus session_cost_total; warns at 80%
- Empty state (no dispatches) returns zeros, not crash
- Tests: empty state, 3-engine mix, budget exhaustion warning, completes in <10ms

#### W11-CROSS-PLATFORM-OBSERVER — cron alternative to Task Scheduler

**Acceptance**:
- `harness observer arm` detects platform: Windows → existing Task Scheduler path, Mac/Linux → cron entry generation
- Generated cron entry uses absolute path to `harness` CLI; uses `*/N * * * *` style for N-minute cadence
- `harness observer disarm` removes the platform-appropriate entry
- `harness observer scheduler-status` reports both platforms with the same JSON shape
- Tests: Linux cron generation (mock `subprocess.run("crontab -l")`), Windows Task Scheduler still works, cross-platform status

#### W11-OBSERVER-WATCHDOG-RECOVERY — self-recovery when watchdog itself hangs

**Acceptance**:
- Dashboard banner / `harness today` output: "observer task last fired Xh ago; run `harness observer restart` to re-arm" when last_pulse > 2× expected interval
- New `harness observer restart` verb that detects the platform + re-creates the scheduler entry
- L4 alarm fires if `harness observer restart` itself fails (escalates to L5 only if 3 consecutive failures)
- Tests: stale-pulse detection, restart command on both platforms, escalation chain

#### W11-PER-CHECK-LATENCY-OBSERVABILITY — preflight check latency telemetry

**Acceptance**:
- `preflight.run_all()` records each check's duration into `.harness/preflight_latency.jsonl`
- `harness today` shows p50/p95 per check over last 24h
- Rolling window auto-prunes entries > 7d old
- Tests: latency recorded correctly, p50/p95 math correct, prune works

#### W11-L5-OUTPUT-CONTRACT — visible output contract for L5 escalations

**Acceptance**:
- `HarnessError` (L5 subclass) emits a stable header `*** OPERATOR ESCALATION (L5) ***` to stderr with: code, plain-language summary, single recommended action
- Observer flags get same template
- `harness today` ALWAYS includes L5 events in last 24h (not buried in `--since-hours` window)
- Tests: each L5 subclass produces the canonical output format

### Wave 11-D — Release gate

#### W11-PYTHON-SDK-API-IMPL — replace stubs with real impl

**Acceptance**:
- `harness.dispatch()` calls `dispatcher.dispatch_packet()` under the hood + returns the new DispatchResult contract
- `harness.retrieve()` and `harness.budget_status()` wired to their implementations
- `mypy --strict` passes on entire public API surface
- All W11 audits re-fired with `--reaudit` (W10-AUDIT-FOLLOWUP-COMMIT-POLICY); mean confidence ≥0.7 per row
- `docs/AGENT_QUICKSTART.md` authored: 1-page guide for a fresh agent cloning the repo
- `OPERATOR_RUNBOOK.md` updated with the agent-vs-human-track split

## Wave 11 closeout (not a separate row, but the wave-exit gate)

When all Wave 11-A through 11-D rows show `Status=shipped` in `coord/STATUS.csv`:

1. Author `coord/reviews/wave-11-closeout.md` with audit roll-up + agent-readiness rating + W12 candidates.
2. Run a NEW "agent-readiness" panel (analog of readiness panel but with 8-10 agentic-coding-agent personas, not human-operator personas).  Target: ≥7/10 YES votes.
3. Re-fire the master audit (40 reviewers) for the post-W11 baseline.
4. Run `harness session ok-to-stop` — exit 0 ends the autonomous loop for the wave.

— End of plan —
