# Changelog

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
