# Post-v1.0.0 master plan

**Source**: 10-agent panel (5 personas × 2 engines), 2026-05-25.
**Engines fired**: DeepSeek (5/5 OK) + MiMo (5/5 OK after 1 serial retry).
**Engines NOT fired**: Kimi (account terminated, W14-KIMI-AUTH-RESTORE L5).
**Personas**: Architect, Operator-UX, Performance, Security-Audit, Velocity — each engine ran each lens independently.

This file is the synthesized "what we run next" derived from the 10 verdicts under [post-v1-master-plan/](.). When the convergence is tight (≥3 of 10 voices), the row goes into THIS WEEK. When only one lens advocates, the row goes to NEXT WEEK or DEFERRED. When two lenses dissent, the dissent is named.

---

## Convergence map

Across 30 row picks (10 personas × 3 each), the strongest convergent themes:

| Theme | Voices | Lens spread |
|---|---|---|
| **Audit-log HMAC chain integrity** | 2 #1-votes (both security) | Security-only but both at #1, conf 0.90+0.95 |
| **Backup secrets redact + integrity verify** | 4 picks across 3 lenses | Security + Architect (both engines) + Operator-UX dry-run |
| **Dispatch health-aware fallback + engine disable** | 5+ picks across 3 lenses | Performance (both engines) + Operator-UX (DeepSeek) + Architect (MiMo health-promote) |
| **Parallel-dispatch RemoteProtocolError retry** | 2 picks (both performance) | Performance lens both engines |
| **Schema versioning** | 2 #1-votes (both architects) | Architect-only #1, dissent from Operator-UX/Performance/Security |
| **Scaffold/codegen for new rows + verbs** | 1 voice (MiMo/Velocity) | Velocity unique to MiMo's engine |
| **`harness start` guided daily workflow** | 1 voice (MiMo/Operator-UX) | Operator-UX unique to MiMo's engine |
| **Key-rotation playbook for Kimi pattern** | 2 picks (security + operator-UX) | Security/key-rotation + Operator-UX/kimi-recovery-guide |

Universal **drop** votes (≥7 of 10 personas):
- CI doc-doc-sync gate — 7 votes drop
- `harness commands --did-you-mean` — 9 votes drop
- Hallucination test harness — 8 votes drop
- Auto-default guardrail CI framework — 5 drop, 4 defer, 1 keep (security)

The biggest **dissent**: Schema versioning. 2 architects rate it #1; Operator-UX/Performance/Security argue it's premature optimization until a real data-structure change forces it. Resolution: defer to Week 3 but lock the *enforcement mechanism* now (one CI test that scans for missing schema_version markers, written but skip-by-default) so it can be unskipped the moment the first schema change ships.

---

## THIS WEEK — ship Mon-Fri 2026-05-26..2026-05-29

Five rows. Two of them (W14-AUDIT-CHAIN-HMAC + W14-DISPATCH-HEALTH-AWARE-FALLBACK) are the security and performance load-bearers — they ship Monday morning. The rest fill the week.

### 1. W14-AUDIT-CHAIN-HMAC

**Title**: HMAC-chain `~/.harness/audit.jsonl` for tamper evidence + key-derived integrity.
**Effort**: M (3-4h).
**Why ship NOW**: 2 of 10 voices rank this #1 (DeepSeek/Security 0.90 confidence, MiMo/Security 0.95) and both name the Kimi termination as proof we need a forensic chain. The audit ledger is the foundation for all future auto-defaults (W13-AUDIT-JSONL ship rationale); without integrity verification, every claim about "what the harness decided" is unverifiable.

**Acceptance criteria**:
- Each new row appended to `audit.jsonl` includes an `hmac` field over `prev_hmac || timestamp || event || redacted_payload` keyed with material from `~/.harness/audit_key` (auto-created on first write, 32-byte random, never logged or backed up).
- New CLI verb `harness audit verify` reads the chain, recomputes HMACs, reports first-broken row index.
- Existing rows backfilled with `prev_hmac=null`; first row uses a static seed HMAC.
- Tampering with any row (delete, reorder, alter character) causes `verify` to fail at the exact location.
- 10+ tests; CI gate proves a corrupted ledger is detectable.

### 2. W14-DISPATCH-HEALTH-AWARE-FALLBACK

**Title**: Dispatch reads engine health before choosing — skip known-dead engines, prune wasted fallback hops, retry transient failures inline.
**Effort**: M (4-5h).
**Why ship NOW**: 5+ voices converge. The failure summary shows 278+ wasted fallback hops in 168h on engines with zero successes (anthropic + gemini). Performance lens quantifies: at $0.01/hop that's $1.39/wk; at $0.10/hop it's $13.90/wk. Operator-UX lens needs `harness engines disable kimi` so the noise stops. Architect (MiMo) wants health to be the routing-decision SoT not a separate flow.

Folds together what 5 personas proposed as separate rows: W14-DISPATCH-FALLBACK-PRUNE (perf-deepseek), W14-DISPATCH-HEALTH-SCORING (perf-mimo), W14-ENGINE-DISABLE-VERB (ux-deepseek), W14-ENGINE-HEALTH-PROMOTE (arch-mimo), and the categorizer-driven retry from W14-DISPATCH-RETRY-FALLBACK-PRIMITIVE (vel-mimo).

**Acceptance criteria**:
- `dispatch()` checks `engine_health_probes.jsonl` + `capabilities.keys_present` before any HTTP call. Engines with `no-key`, `terminated`, or rolling 24h success rate <50% are skipped from the fallback chain.
- New `harness engines disable <name>` / `harness engines enable <name>` (persisted to `state/engine_health.json`); disabled engines are excluded from BOTH primary and fallback. Engine probing continues for visibility but routing-impact is zero.
- New `harness engines --fallback-policy` shows the effective fallback order with skip reasons.
- Categorizer (W13-ENGINE-FAILURE-VISIBILITY) drives auto-retry: `transient` → 2 retries on same engine with 1s/2s backoff; `terminated` / `auth-failed` → never retried, immediately fallback; `quota-exceeded` → fallback now + 15min cooldown before next attempt.
- Every retry + fallback decision lands its own row in `audit.jsonl` with `decision_reason` field.
- `DispatchResult` gains `engine_actual`, `retries`, `fallbacks_used` fields.
- Tests: missing-key engine never called, terminated engine immediately fallback, transient retried 2x then fallback, 0 regressions in serial dispatch.

### 3. W14-BACKUP-MANAGER

**Title**: Unified `BackupManager` — secret redaction during create, SHA256 integrity verify on restore, `--dry-run` to preview.
**Effort**: L (5-6h).
**Why ship NOW**: 3 lenses converge across both engines. Security lens (both engines) says backup tarballs can contain the dead Kimi key. Architect lens (DeepSeek + MiMo) wants the scattered backup logic collapsed into one class. Operator-UX (MiMo) wants `--dry-run` to preview contents before committing.

Folds: W14-BACKUP-MANAGER-REFACTOR (arch-deepseek), W14-BACKUP-SECRETS-REDACT (sec-deepseek, arch-mimo), W14-BACKUP-DRY-RUN (ux-mimo), W14-BACKUP-PREFLIGHT-SCAN (sec-mimo).

**Acceptance criteria**:
- `src/harness/backup.py` exposes `BackupManager` class with `create(target_dir, dry_run=False)` and `restore(archive, verify=True)` methods.
- `create()` runs every file through the W13-AUDIT-JSONL 7-pattern redaction (`redact_secrets`) before tar inclusion; writes a manifest JSON with `created_at`, `schema_version: 1`, `file_list`, `sha256sums`, `redacted: true`, `patterns_applied: [...]`.
- `create(dry_run=True)` lists files that would be archived + flags any containing secrets + shows tree+sizes; runs <2s.
- Pre-create scan: high-entropy strings AND known prefixes (sk-, tp-, AIza) in tracked files raise a warning + `--force` to bypass.
- `restore(verify=True)` recomputes SHA256, rejects mismatches with `IntegrityError` naming the offending file.
- CLI: `harness backup create [--dry-run]` and `harness backup restore <archive>` delegate to the class.
- 12+ tests including: redact_secrets covers all 7 patterns in archived files, integrity-fail-on-modification, dry-run lists no actual archive, manifest JSON parsable.

### 4. W14-KEY-ROTATION-PLAYBOOK

**Title**: `harness env rotate <engine>` — guided key-rotation walkthrough with live verification.
**Effort**: S (2h).
**Why ship NOW**: 2 voices propose nearly identical rows (security/key-rotation + operator-UX/kimi-recovery-guide), both as direct response to the Kimi termination. A non-technical operator should not have to reverse-engineer env-var + backup cleanup manually when an engine dies.

**Acceptance criteria**:
- `harness env rotate kimi` prints a numbered playbook with the 4 options from W14-KIMI-AUTH-RESTORE (email support, replace key, switch to Platform endpoint, drop kimi), executable in-terminal.
- After the operator pastes the new key, the command runs `probe_engine_live` and reports `up` / `terminated` / `auth-failed`.
- A `~/.harness/key_rotations.jsonl` event log records each rotation: engine, timestamp, fingerprint (HMAC-SHA256 of new key, no plaintext), prior fingerprint if available.
- Inline tip in `harness engines --health` output: when an engine is `terminated`, the line ends with `→ run 'harness env rotate <engine>' for the recovery playbook`.
- 6+ tests with mock engine.

### 5. W14-PARALLEL-DISPATCH-RETRY-FIX

**Title**: ThreadPoolExecutor-wrapped retry for `RemoteProtocolError` so parallel dispatch survives MiMo's transient race.
**Effort**: S (2h).
**Why ship NOW**: 2 of 10 voices flag this (both performance), with concrete production evidence — the Friday release-gate panel AND today's master-plan panel both hit it. The per-engine retry in `transport.py` doesn't cover the parallel-dispatch race; a single transient failure currently aborts the entire parallel batch.

**Acceptance criteria**:
- `concurrent.futures.ThreadPoolExecutor`-wrapped dispatch (used by panel scripts) catches `RemoteProtocolError` once per future and re-queues with 1s backoff.
- Retry attempts logged to `audit.jsonl` with `retry_reason: parallel_dispatch_race`.
- Existing `_retry_one` helper in `scripts/post_v1_master_plan_panel.py` superseded by a `harness.engines.parallel_dispatch` helper (importable from scripts).
- 8+ tests: mock that fails once then succeeds, restoration of response; 0 regressions in serial path.

**Estimated week-total**: ~17-19h. Achievable in 4 days of focused work + the rest of the week left for the audit on each row.

---

## NEXT WEEK — ship Mon-Fri 2026-06-01..2026-06-05

### 6. W14-SCAFFOLD-COMMAND

**Title**: `harness new verb <name>` / `new test <name>` / `new row <ID>` — collapse the 4-file ritual to 2 minutes.
**Effort**: M (4-5h).
**Why NEXT WEEK not THIS WEEK**: Single-voice (MiMo/Velocity 0.82), but its leverage is purely compound — the only reason to ship it is "all future rows are cheaper." Defer one week to let THIS WEEK's load-bearing rows land first; once they're stable, the scaffolder pays for itself starting from row #6.

### 7. W14-GUIDED-DAILY-WORKFLOW

**Title**: `harness start` — interactive daily workflow (engine health → budget → backup status → today's priority).
**Effort**: M (4-5h).
**Why NEXT WEEK not THIS WEEK**: Single-voice (MiMo/Operator-UX 0.90 confidence), but the underlying signals it surfaces (engine health, budget, backup status) all get better in THIS WEEK's ships. Better to wait so `harness start` shows the post-Week-2 state, not the pre-Week-2 state.

### 8. W15-SCHEMA-VERSION-MANDATE (deferred from Week 2)

**Title**: Add `schema_version: 1` to all persistent JSONL/CSV files + a CI gate (`test_schema_versions_present.py`) that's currently skip-by-default and unskip-when-first-change-ships.
**Effort**: M (4-5h).
**Why DEFERRED from THIS WEEK**: Both architects rank this #1 (DeepSeek + MiMo), but 3 other lenses argue it's premature optimization. Compromise: ship the INFRASTRUCTURE (version field + CI test) now, defer the enforcement (test stays skipped) until the first real data-structure change. The infrastructure costs ~1h; un-skipping costs 0h when needed.

---

## CONFIRMED DROPS — not coming back this month

Universal-vote drops (≥7 of 10 personas):

- **CI doc-doc-sync gate** (7 votes drop) — symmetric `test_docs_*` gates already exist; a third inter-doc consistency gate is polish without compound leverage.
- **`harness commands --did-you-mean`** (9 votes drop) — pure typo UX, zero structural / security / velocity value.
- **Hallucination test harness** (8 votes drop) — research-grade; ship only if a real hallucination causes actual data corruption.
- **Auto-default guardrail CI framework** (5 drop + 4 defer) — premature until the first concrete auto-default ships; build the template alongside the first auto-default rather than upfront.

Already-deferred (Week 2/Week 3 holding):

- **W13-DISK-PRUNE + W13-LOCK-DEPS** — 4 voices say drop / defer; no voice ranks them in top 3. Move to "do when an actual disk-pressure or dep-version incident occurs."

---

## SINGLE MOST IMPORTANT ACTION (right now)

**Ship W14-AUDIT-CHAIN-HMAC Monday morning.** Both security personas (the only two of 10 who fully agree on a #1) rank this above everything else, both at 0.90+ confidence. The Kimi termination event is fresh evidence that the harness needs forensic-grade audit integrity. The W13-AUDIT-JSONL ledger is the foundation everything else builds on; chain it now and every subsequent auto-default + dispatch decision becomes verifiable.

After it lands Monday afternoon, the rest of THIS WEEK is mechanical execution of #2-#5.

---

## Lens dissent (named, not resolved)

| Question | Architect (2) | Operator-UX (2) | Performance (2) | Security (2) | Velocity (2) | Master-plan call |
|---|---|---|---|---|---|---|
| Schema versioning now? | YES (#1) | NO (premature) | NO (no perf impact) | NO (defer) | NO (no compound) | Ship INFRA now, defer ENFORCEMENT (Week 3 row, hold) |
| Backup integrity / redaction now? | YES (#1-2) | YES (#3 dry-run) | KEEP (Week 2) | YES (#2) | DROP (Week 2 hygiene) | YES — W14-BACKUP-MANAGER ships THIS WEEK (collapses 4 voices) |
| HMAC audit chain now? | (silent) | (silent) | (silent) | YES (#1 unanimous) | (silent) | YES — security lens carries; W14-AUDIT-CHAIN-HMAC THIS WEEK |
| Dispatch tiers / health-routing? | KEEP (health-promote) | YES (engine-disable) | YES (#1-3) | (silent) | YES (retry-primitive) | YES — W14-DISPATCH-HEALTH-AWARE-FALLBACK THIS WEEK |
| Scaffold/codegen for new rows? | (silent) | (silent) | (silent) | (silent) | YES (#1) | YES NEXT WEEK — single voice but high compound |
| `harness start` daily workflow? | (silent) | YES (#1) | (silent) | (silent) | (silent) | YES NEXT WEEK — wait for Week 2 signals |

Three lenses (Operator-UX/Performance/Security) explicitly DON'T want schema versioning urgent. Two architects rank it #1. The compromise (ship infra, defer enforcement) lets architects lock in the pattern without imposing it on the others.

---

## Confidence

The master plan has **0.83 combined confidence** — average across the 10 panelists' self-rated confidence (range 0.7 to 0.95). The lowest-confidence pick is MiMo/Architect at 0.7 (acknowledging incomplete observation of repo state). The highest is MiMo/Security at 0.95 on HMAC chain.

What would lower confidence: discovering that an out-of-band integration (e.g., the warehouse project) already consumes `audit.jsonl` in a way that the HMAC chain would break. We need to verify there are no external consumers before Monday's HMAC ship.

What would raise confidence: a 2-engine ratification pass before Monday morning (15 min, ~$0 cost) asking each engine "given the master plan synthesis above, what was missed?"

---

## How this file was made

`scripts/post_v1_master_plan_panel.py` fires 10 dispatches (5 personas × 2 engines). Each persona was given the same source pack (CURRENT_PLAN.md + v1.0.0 release notes + Friday release-gate verdict + 5 fresh STATUS.csv rows + live capability snapshot + live engine health + 7-day failure summary, total 30,758 chars) and asked to render a focused stance through their lens. The 10 responses live alongside this file under [post-v1-master-plan/](.). 9 dispatches succeeded on first parallel attempt; 1 (mimo/security-audit) needed a serial retry past a `RemoteProtocolError` — this is exactly the pattern W14-PARALLEL-DISPATCH-RETRY-FIX (THIS WEEK row #5) is for.

To re-fire: `python scripts/post_v1_master_plan_panel.py`. To synthesize fresh: read all 10 verdicts + write a new MASTER_PLAN.md.

---

## POSTSCRIPT — Kimi termination root-cause investigation (added 2026-05-25 evening)

After the panel landed, operator flagged that the Kimi termination may affect other users too (provider-side sweep, not single-account flag) and asked for an investigation + alternatives. Findings in [kimi-termination-investigation/FINDINGS.md](../kimi-termination-investigation/FINDINGS.md).

### Headline

The harness ships a **User-Agent spoofing default** (`claude-code/0.1.0` — see [src/harness/engines/concrete.py:69-76](../../../src/harness/engines/concrete.py)) to bypass Kimi Code's UA allowlist. Kimi's [Community Guidelines](https://www.kimi.com/code/docs/kimi-code/community-guidelines.html) explicitly prohibit client-identity tampering ("不伪造或篡改客户端身份信息"). Moonshot now actively detects + terminates accounts using this pattern. The operator's account was almost certainly terminated for this reason, and a new key would be re-terminated within one or two sessions.

### Updates to THIS WEEK / NEXT WEEK lists

**Insert as THIS WEEK row #6** (between #5 W14-PARALLEL-DISPATCH-RETRY-FIX and the NEXT WEEK section):

#### 6. W14-KIMI-REPLACEMENT-WITH-GLM

**Title**: Drop Kimi from default pool + add GLM-5.1 (Zhipu) as new engine adapter using OpenAI-compatible chat-completions schema.
**Effort**: M (4-5h).
**Why ship NOW**: The investigation confirms Kimi is unrecoverable for xaxiu-harness as-built. W14-KEY-ROTATION-PLAYBOOK (THIS WEEK row #4) is wasted effort on the Kimi case unless we first replace the spoofed UA with a legitimate one (which means Kimi will deny us at the gate anyway). GLM-5.1 is open-weight under MIT, OpenAI + Anthropic API compatible, $0.60/$2.00 per M tokens, and benchmarks at 85 on BenchLM / 77.8% SWE-bench Verified — close to Claude Opus 4.5 on agentic coding. Zero termination risk.

**Acceptance criteria**:
- `src/harness/engines/concrete.py`: change `_make_kimi_user_agent()` default from `claude-code/0.1.0` to `xaxiu-harness/1.0` (TOS compliance — accepts that Kimi will now deny xaxiu-harness traffic at the gate, which is the correct outcome).
- New `src/harness/engines/glm.py` (or extend concrete.py): `GLMConcrete(StreamingTransport)` adapter pointing at the public GLM Coding API endpoint with OpenAI-compatible chat-completions schema. Uses `GLM_API_KEY` env var (added to `_constants.py::API_KEY_ENV_VARS`).
- `SUPPORTED_BACKENDS` includes `"glm"`; `get_engine("glm")` returns a working instance.
- `harness engines --health` probes glm successfully.
- 12+ tests modeled on `test_engines_concrete_boundary.py`.
- Default fallback chain (per W14-DISPATCH-HEALTH-AWARE-FALLBACK) is `[deepseek, glm, mimo]`. Kimi is removed.
- Documentation: AGENT_QUICKSTART.md notes Kimi is deprecated and GLM is the replacement; release notes for v1.0.1 cover the change.

### Update to row #4 — W14-KEY-ROTATION-PLAYBOOK

The playbook should NOT recommend "email Moonshot support to restore Kimi" as a default path — it should explain the TOS violation, note that restoration is unlikely without a redesign, and recommend the operator skip Kimi entirely. The playbook still applies for engines that fail for non-TOS reasons (quota / billing / leaked key).

### Updates to W14-KIMI-AUTH-RESTORE row in STATUS.csv

The existing W14-KIMI-AUTH-RESTORE row says "operator action options: (a) email support, (b) get new account, (c) migrate endpoint, (d) drop kimi." After this investigation, **option (d) is the only one that doesn't recur**. Options (a)-(c) all preserve the underlying UA-spoofing violation and Moonshot will re-terminate within one or two dispatches.

### New deferred row

**W15-KIMI-LEGITIMATE-INTEGRATION** (L, ~12-15h, deferred): if Moonshot ever publishes an "approved third-party agent" registration process, file xaxiu-harness as a legitimate client, replace the spoofed UA with the issued one, and restore Kimi to the engine pool. Currently unfileable — no such registration program exists at platform.moonshot.cn or platform.moonshot.ai.

### Confidence update

Headline confidence remains 0.83 for the original panel synthesis. The Kimi-replacement diagnosis is **0.92 confidence** — direct provider-side evidence (the 403 body text + the community guidelines + third-party confirmations of the UA-allowlist enforcement pattern) plus the harness's own code comment acknowledging the workaround.

