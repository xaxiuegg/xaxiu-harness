# Changelog

## v0.5.6 — 2026-05-28 (conversational re-asks + history browser)

### Phase 2.2 + 2.3 of agentic-operator roadmap

Two related verbs that turn `coord/reviews/ask-*/` from a write-only
forever-record into a queryable + replayable history.

**`harness ask --rerun <dir> [--escalate {audit|panel}]`** (Phase 2.2)

Re-asks the question from a prior ask-* dir.  Without `--escalate`,
inherits the parent's mode + engines.  With `--escalate audit`,
upgrades a routed answer to a producer→auditor flow on the same
question.  With `--escalate panel`, promotes to the 3-engine fanout.
The new ask's `summary.json` carries `parent_id`, `parent_mode`,
`escalated_from`, and `escalated_to` for traceability.

```bash
harness ask --rerun coord/reviews/ask-...                # repeat
harness ask --rerun coord/reviews/ask-... --escalate audit
harness ask --rerun coord/reviews/ask-... --escalate panel
```

Conflicts: `--rerun` cannot be combined with positional QUESTION or
`--file` (the question comes from the rerun dir).  `--escalate`
without `--rerun` emits a warning + is ignored.

**`harness ask-history` + `harness ask-show <id>`** (Phase 2.3)

Browse past `harness ask` outputs without leaving the CLI.

```bash
harness ask-history --last 10              # newest 10
harness ask-history --mode audit           # audit only
harness ask-history --verdict FAIL         # past failures
harness ask-history --format json | jq     # programmatic
harness ask-show ask-20260528-...          # render one
harness ask-show ask-20260528-... --format json
```

The natural pairing: use `ask-history` to find a parent id, then
`ask --rerun <dir>` to replay it.

### Module + tests

- New: `src/harness/ask_history.py` (`list_asks`, `load_ask`,
  `render_history_text`, `render_ask_text`).  20 tests in
  `tests/test_ask_history.py`.
- New CLI verbs in `src/harness/cli.py`: `ask-history`, `ask-show`,
  plus `--rerun` + `--escalate` flags on the existing `ask` command.
- `tests/test_ask.py` gains a `TestAskRerun` class (7 tests covering
  question inheritance, --escalate audit/panel/none, conflicts with
  positional/file, missing question.md error, --escalate without
  --rerun warning).
- Agent-instructions templates updated: ask section gains
  `--rerun`/`--escalate` examples; new "Past asks" subsection (claude-md
  Section 5) covers `ask-history` + `ask-show`.

W14-ASK-RERUN + W14-ASK-HISTORY.

## v0.5.5 — 2026-05-28 (harness introspect — single-call discovery primitive)

### Phase 2.1 of agentic-operator roadmap

New verb **`harness introspect`** gives a fresh Claude Code session ONE
call to learn the harness's full surface + current state, instead of
issuing 5+ individual queries to discover the same information.

```bash
harness introspect                  # human-readable text
harness introspect --format json    # structured (agent-parse this)
harness introspect --probe          # also live-probe engines (~few cents)
```

The snapshot covers:

- Version + repo path + timestamp
- **Verbs**: ask modes / proxy state with 5 upstream options /
  engines describe count / xaxiu-swarm sibling presence
- **Engines**: per-engine key presence + count + protocols +
  UA-gating + recommended task classes (from the Phase 1.2 metadata)
- **Agent-instructions snippet**: installed-vs-current hash check
  (warns "STALE" when the snippet at `~/.claude/CLAUDE.md` predates
  the current repo — exactly the gap we hit on the operator's machine)
- **Wrappers**: per-provider Claude Code shortcut installed + on-PATH
- **Doctor**: 9-check summary with first-issue hint + fix command
- **Recent asks**: last 5 outputs with mode + verdict + engines + cost

Default is read-only (no live network).  `--probe` opts into per-engine
round-trips.

### Module + tests

- New: `src/harness/introspect.py` (`build_snapshot()`, `render_text()`,
  6 private collectors).  28 tests in `tests/test_introspect.py`.
- New: `harness introspect` CLI verb in `src/harness/cli.py`.

### Agent-instructions template update

All 3 formats (claude-md / prompt / short) now lead with
"**Start here — `harness introspect`**", giving fresh sessions a
clear single-call entry point.  Regression tests extended to require
the introspect mention in every format.

W14-INTROSPECT.

## v0.5.4 — 2026-05-28 (agent-instructions templates surface today's verbs)

### Phase 1.3 of the agentic-operator roadmap

The agent-instructions snippet that `install-agent-instructions` lands
in `~/.claude/CLAUDE.md` was missing Phase 1.1 + 1.2 capabilities:

- The 5-upstream proxy + `--upstream` flag (Phase 1.1)
- The engine metadata verbs `describe` + `compatibility-matrix` (Phase 1.2)
- A "verify engine health first" prompt
- An explicit "DO NOT hand-roll a shim — the subprocess upstreams already
  do it TOS-compliantly" warning

A fresh Claude Code session reading only the v0.5.3 snippet could
follow the routed-default + audit + panel + proxy + swarm flows but
would still source-spelunk for engine-specific questions and still
miss `--upstream` when wiring third-party tools to MiMo.  v0.5.4 fixes
that.

### What changed in all 3 template formats (claude-md / prompt / short)

- **Proxy section**: enumerates all 5 upstreams + shows
  `harness proxy upstreams` listing verb + explicit anti-shim warning.
- **NEW Discovery section**: `harness engines describe`,
  `compatibility-matrix`, `recommend` with the canonical
  MiMo-dual-protocol worked example.
- **NEW "Before reaching for any of this" callout**: prompts agents to
  run `harness doctor` FIRST and notes Kimi is no longer in the
  $195/mo strategic-plan rotation.

### Regression locks (in `tests/test_agent_instructions.py`)

- `test_install_uses_current_template` extended with v0.5.4
  fingerprints (`--upstream`, `harness proxy upstreams`,
  `mimo-via-claude-code`, `harness engines describe`,
  `compatibility-matrix`).
- New `test_all_formats_surface_discovery_verbs` — locks all 3 formats
  mentioning `harness engines describe` + `--upstream`.

To refresh the snippet currently installed at `~/.claude/CLAUDE.md`:

```
python -m harness install-agent-instructions --force
```

Fresh-session-confidence-with-just-snippet score est 6/10 → 8/10.

W14-ASK-DOCS-PHASE-1-3.

## v0.5.3 — 2026-05-28 (engine metadata as queryable surface)

### `harness engines describe <name>` + `harness engines compatibility-matrix`

New subcommands surface per-engine metadata that previously lived only in
source docstrings, code comments, and scattered memory entries.  Closes
three specific transcript hiccups by making 1 call do what previously
needed 4-9 source-spelunking tool calls.

```bash
harness engines describe mimo-via-claude                # human-readable
harness engines describe mimo-via-claude json           # JSON
harness engines compatibility-matrix                    # N×M table
harness engines compatibility-matrix --json             # machine-readable
```

The `describe` output covers: vendor, protocol surfaces (e.g. MiMo
exposes BOTH `openai` and `anthropic` — the canonical confusion
documented inline), key env + valid prefixes, UA-gating notes,
default + available models, latency class, per-smoke cost, best-fit
task classes, and consumption surfaces (HTTP direct / proxy upstream
/ Pattern B / swarm).

The `compatibility-matrix` answers the question "how can I reach
engine X from context Y?" — a question that took an agent 9 tool
calls to answer manually in the 2026-05-27 transcript.

**New module**: `src/harness/engines/metadata.py` — `EngineMetadata`
frozen dataclass + registry of 6 engines (mimo / deepseek / kimi /
qwen via-claude, plus anthropic + gemini for reference) +
`describe(name)` lookup + `compatibility_matrix()` builder.

Storage shape is hardcoded for now; a future refactor could pull from
an `@engine_metadata` decorator on each adapter class.  The
dataclass shape is stable so that's an additive move.

W14-ENGINE-METADATA.  Phase 1.2 of the agentic-operator roadmap.

## v0.5.2 — 2026-05-28 (harness proxy --upstream)

### `harness proxy start --upstream <name>` — multi-upstream proxy

The proxy was previously hardcoded to Kimi (`api.moonshot.cn`).  It now
supports five upstreams, picked via `--upstream <name>` (default
`kimi-http` to preserve pre-v0.5.2 behavior).

**HTTP-direct upstreams** (OpenAI-compatible chat-completions, ~100ms
overhead per request):

- `kimi-http` — Kimi (Moonshot).  Pre-v0.5.2 behavior.
- `deepseek-http` — DeepSeek v4.  PAYG.
- `qwen-http` — Qwen 3.6 Plus via Alibaba DashScope.  PAYG.

**Claude-Code-subprocess upstreams** (TOS-compliant for User-Agent-
gated providers, ~5-7s subprocess boot per request):

- `mimo-via-claude-code` — MiMo Token Plan SGP.  Routes through `claude
  --bare --print --output-format json` with the right ANTHROPIC_*
  env vars; translates the Anthropic-shape response back to OpenAI
  shape.  Replaces the standalone shim some integrations were forced
  to hand-roll.
- `kimi-via-claude-code` — Kimi Code subscription via the same pattern.

Direct-HTTP routes can be rejected by UA-gated providers (`tp-*` MiMo
keys, Kimi Code subscription).  Subprocess routes spawn the legitimate
`claude` binary whose User-Agent is on the providers' allowlists — no
spoofing, TOS-compliant.

**New verbs:**

```bash
harness proxy upstreams                 # list all 5 with transport + key env
harness proxy upstreams --format json   # machine-readable
harness proxy start --upstream mimo-via-claude-code
harness proxy start --upstream deepseek-http
```

**New modules:**

- `src/harness/proxy/upstreams.py` — registry of `UpstreamSpec`
  (frozen dataclass) and `get_upstream(name)` / `list_upstreams()`.
- `src/harness/proxy/handlers.py` — `http_handler`,
  `claude_code_subprocess_handler`, `dispatch_to_upstream` + the
  Anthropic-to-OpenAI translation helpers.

`create_app(upstream="...")` accepts either an upstream name or a
fully-constructed `UpstreamSpec`.  `upstream_url=` is still honored
as an override for the spec's `base_url` (back-compat for callers
predating the registry).

`/healthz` response now includes the active upstream's name,
transport, base_url, and default_model.

W14-PROXY-UPSTREAMS.

## v0.5.1 — 2026-05-27 (harness ask redesign)

### Breaking: `harness ask` default changed from 3-engine panel → routed single engine

Bare `harness ask "..."` is now a single-engine call routed through
`harness engines recommend default` (→ mimo-via-claude, ~$0.01-0.05,
~30s).  FOUR modes:

- **routed (default)** — 1 engine via recommender.  Daily-driver.
- **`--task <class>`** — routed default with a different task class
  (latency / verbose / cost / high-volume / multimodal / audit).
- **`--audit`** — producer → auditor flow (2 engines, sequential).
  Producer answers; auditor (picked via `recommend('audit',
  exclude={producer})`) critiques the answer and returns a structured
  VERDICT: PASS / PARTIAL / FAIL.  ~$0.05 / ~60s.  Designed for
  catching hallucinations and stress-testing factual claims.
- **`--panel`** — preserves the pre-v0.5.x 3-engine parallel fanout
  (~$0.20-0.30, ~60-120s).  Opt-in for high-stakes design crossroads.
- **`--engines X,Y,Z`** — explicit pin, unchanged.  HANDOFF.md step 7
  + scripted callers still work.

`summary.json` gained a `mode` field (`"routed"` / `"panel"` /
`"audit"`).  Routed mode writes question.md + `<engine>.md` +
summary.json (no packet.md — the lone engine file IS the synthesis-
ready artifact).  Panel + audit modes write packet.md as before.
Audit mode also writes `producer-<engine>.md` + `audit-<engine>.md`
(role-prefixed filenames) and surfaces the parsed verdict in
`summary.json` under `verdict.{verdict, summary, corrections,
missed, overall, raw}`.

New helpers: `harness.audit_prompt.build_audit_prompt()` (the
inspectable producer-answer-plus-rubric template) and
`parse_audit_verdict()` (forgiving regex parser that surfaces
malformed verdicts as `"UNKNOWN"` rather than silently treating
them as PASS).

W14-ASK-ROUTED-DEFAULT + W14-ASK-AUDIT.

### Docs sweep + `agent-instructions` templates (W14-ASK-DOCS)

Docs updated end-to-end to reflect the new ask shape:

- `docs/OPERATOR_GUIDE.md` § 2.5 — full rewrite with 4-shape table,
  per-mode sample outputs, cost-by-mode table, AND a worked example
  for the hallucination self-check pattern (MiMo conflation scenario
  from a real transcript review).
- `docs/OPERATOR_GUIDE.md` § 3.1 — drops "90% of the time" framing;
  shows the four ask shapes side-by-side.
- `docs/OPERATOR_GUIDE.md` § 8.2 — cost table refreshed by mode.
- `docs/AGENT_REFERENCE.md` § 8 — full rewrite.  New subsections:
  routed default, `--audit` (with programmatic verdict-access code
  example), `--panel`, when NOT to reach for `harness ask`, the
  proxy at 127.0.0.1:7879 (Gap A), `xaxiu-swarm` sibling repo
  (Gap A), empirical routing.
- `docs/HANDOFF.md` Piece B — drops "ask 3 AI models the same
  question in parallel" framing; shows the three daily-driver
  commands.
- `src/harness/cli.py` `agent-instructions` templates (all 3
  formats: claude-md / prompt / short) — full rewrite.  Templates
  now cover BOTH `harness ask` (with the 3 modes + when NOT to
  use) AND the proxy AND xaxiu-swarm.  The harness proxy and
  sibling swarm repo were undocumented in agent instructions
  before W14; both are now first-class.  Re-run
  `python -m harness install-agent-instructions --force` to
  refresh the installed snippet at `~/.claude/CLAUDE.md`.

## v0.5 — 2026-05-21 (autonomous session arc)

22 sequential commits, 50+ shipped STATUS rows, tests 711 → 1106 (+395).
Architecture is now production-hardened end-to-end with operator-config
knobs, failure-recovery surface, and a programmatic anti-premature-stop
gate.

### Phase 4 — v2 production hardening
- `3003eeb` **V2-MOCK-ENGINE** — `src/harness/engines/mock.py` enables offline smoke; mock excluded from auto-fallback chain via `_NON_PRODUCTION_BACKENDS`
- `6bef07f` **COORD-WORK-WIRE + WORKER-RUN-ENGINE + COORD-WORKTREE-CREATE** — worker dispatches FILE/REPLACE prompts, applies edits in per-worker git worktrees, coordinator creates worktrees pre-spawn
- `9c05e95` **V2-FIRST-RUN** — first end-to-end smoke test against tmp git repo; caught 4 production-blocking gaps (planner adapter missing, no PROJECT_ROOT placeholder resolution, no lazy `init_db`, stale `ActiveDispatch` literal)
- `815de8b` **INTEGRATOR-GIT-MERGE** — `_merge_worker_branches` honours `WavePlan.integration_strategy`
- `53de7dc` **PROXY-AUTOSTART + OPERATOR-DIRECTIVES-PROMOTION** — `coord run --proxy auto`; 3 new YAML sub-schemas (SessionHandoffThresholds, KillConditions, ProductionHygieneBalance)
- `ab62db4` **CHAT-OBSERVER + COORD-LOG-STREAM + KILL-CONDITION-WIRING** — chat-transcript audit; `coord watch`; runner enforces YAML kill caps with L4 escalation

### Phase 5 — operator UX polish
- `d60923f` **DASHBOARD-V2-ROUTES + PACKET-FANOUT-RULE** — `/v2/runs`, `/v2/runs/<id>/workers`, `/v2/proxy-state`; auto-fanout rule formalised in `dispatch-rules.md`
- `f5ed5dd` **WORKER-TOKEN-COST-TAG + DASHBOARD-WS-V2-STREAM + COORD-RUN-LIST-VERB + PROXY-ADMIN-RESET** — budget meter sees v2 runs; WS embeds `v2.cost`; `coord list`
- `dd5e672` **CHAT-OBSERVER-AUTO-ARM + ENGINE-COOLDOWN-VIZ + COORD-NOTIFY** — `observer install-scheduler --include-chat`; `engines cooldowns`; `notify.json` + webhook
- `445b55b` **WORKER-RESUME-ON-RETRY** — `coord retry --worker-id`
- `c0f865d` **Phase-5 closeout** — `coord plan-from-description`; worker step-level progress jsonl; `/v2/runs/<id>` HTML
- `9fe2396` **COORD-REPLAN-ON-FAIL** — `coord replan --run-id` with failed-worker feedback
- `2e4b2da` **RUN-TAG-LABEL + COORD-RUN-DRY-RUN** — `--label` propagates through RunState + `list_runs`; `--dry-run` short-circuits before engine spend

### Phase 6 — hardening + security
- `e8c77a6` **FIRST-RUN-DOCTOR + DB-CORRUPT-RECOVERY + COST-LEDGER-EXPORT + PACKET-INJECTION-FILTER** — `harness doctor` traffic-light preflight; SQLite integrity_check + auto-restore on init; `budget export-daily`; dispatcher refuses packets containing env/DPAPI/network exfil patterns
- `c0c156a` **COORD-CANCEL + REPLAY-COORD-RUNS + DASHBOARD-COST-PANEL + ENGINE-PROBE-QUOTA + AUTO-QUARANTINE-KEY** — graceful `coord cancel`; replay extends to v2 run_ids; dashboard live spend; proxy probes parse rate-limit headers; 3-flap-in-60min auto-quarantine
- `58ca051` **LOCK-COORD-DIR + SPEC-PROVENANCE-TRAIL** — stdlib-only file lock for parallel-session safety; `spec-register` + `spec-verify` for tamper detection

### Integration wires + premature-stop prevention
- `8112e76` **WIRE-STALL-DETECT + WIRE-AUTOLINT + WIRE-PROVENANCE-VERIFY + WIRE-FLAP-ESCALATION + SESSION-OK-TO-STOP-GATE** — coordinator surfaces stalled workers as L4; planner auto-lints before engine dispatch; dispatcher auto-verifies provenance when registered; flap writes L4 escalation file; **`harness session ok-to-stop`** is the deterministic gate that prevents premature stop
- `d73323c` **WIRE-DB-SNAPSHOT-CRON + WIRE-OBSERVER-AUTOARM-ALL** — `harness state snapshot/snapshot-schedule/snapshot-unschedule`; `observer install-scheduler --all` arms chat + cycle + retro + db-snapshot + cost-export
- `6706efc` **DISK-FULL-GUARD** — `status.store.write_status` refuses below 10MB free; `.bak` rotation + post-replace SHA verify + restore-from-bak on corruption detection

### Hygiene + supporting
- `f8dec28` **WORKER-HEARTBEAT + SPEC-LINT + COORD-RERUN-FAILED** — per-step heartbeat sentinel + `detect_stalled_workers`; `harness lint-spec` preflight; `coord rerun-failed` chains replan+run+integrate
- `82d180c` **doc-sync + .claude hooks + .gitignore** — CLAUDE.md to v0.4; warehouse-mining Stop + PostToolUse hooks
- `244e152` **15 production rows added to STATUS + 3 v2-capability packets drafted**
- `259f0fd` **engine routing** — KimiConcrete via localhost proxy when available
- `80dcff9` **DPAPI fix** — multi-key resolution + empty-stub guard + env reporting

### Mechanism: prevent future premature-stop incidents

Codified after the 2026-05-21 incident where the AI declared "session
complete" at 10MB transcript despite STRONGLY threshold being 18MB:

- `src/harness/session/stop_check.py` — deterministic `ok_to_stop()`
- `harness session ok-to-stop` CLI — exit-0 only when STRONGLY/CRITICAL or operator-flag or genuine drain
- Chat Observer `premature_stop` pattern (HIGH severity)
- `coord/dev_loop/manager.md` step 0.6 — mandates the check before any stopping reply
- Memory: `feedback_no_premature_stop.md`

### Test count
- Pre-session: 711
- Post-session (this CHANGELOG): 1106
- Delta: +395
- Known issue: 1 Windows-concurrency flake in `test_state_files::test_concurrent_update_engine_health` (pre-existing, not session-introduced)

---

## Older versions

(Previous version notes live in commit history; this changelog
started 2026-05-21 with v0.5.)
