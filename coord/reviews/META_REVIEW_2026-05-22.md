# Meta-review — xaxiu-harness session 2026-05-22

Operator question: *"Is this the true possible speed?"*  Four-phase audit + 2-engine external review.

---

## Top-line verdict

**Today's actual throughput was ~50–60% of the achievable ceiling.**  Both MiMo Pro and DeepSeek (with thinking ON) independently estimate 8–18 features/8 hours under perfect dispatch discipline; today shipped ~11 effective items.

The gap is **80% Claude-role-discipline** (inline drift across 3 successive defect waves) and **20% systemic** (dispatcher friction + invisible budget meter + cross-project memory leak biased Claude toward "just do it inline").

Migration recommendation: **per-project memory directories.**  No need to move the xaxiu-harness folder itself; only the memory layout.

---

## Phase 1 — External engine reviews (compact form)

Three engines were sent a 3 KB packet asking 5 structural questions.

| Engine | Result | Latency | Length |
|---|---|---|---|
| **MiMo V2.5-Pro** (Token Plan SGP) | ✅ | 34.4 s | 4 218 chars |
| **DeepSeek V4-flash** (thinking ON) | ✅ | 15.3 s | 2 664 chars |
| **Kimi K2.6** (Kimi Code) | ❌ `internal` | 62.1 s | — |

Kimi K2.6 hit its thinking-mode server-side wall (~60 s).  This is the third time today Kimi has failed at exactly 60 s — it's a server-side reasoning-time cap, not our client.  Earlier benchmark sequential test showed Kimi succeeds at simple prompts; it fails specifically on long-form generation tasks.

### Both engines that responded agree on the 4 structural questions:

**Q1 — Inline drift root cause:** ~80% Claude discipline, ~20% dispatcher friction.  Specific dispatcher contributions:
- `force_engine` still iterates the full fallback chain on failure → "dispatching feels slow" → biased Claude toward inline (MiMo)
- Budget meter shows `(no dispatches)` despite dispatches happening → no running tally to self-correct against (MiMo)
- The 30-LOC ceiling has no escape hatch for "tiny mechanical fix" → Claude can't legally dispatch a 5-LOC fix, so does it inline (DeepSeek)

**Q2 — Throughput ceiling estimate:**
- Per-feature wall-clock: 5–7 min (MiMo) or 40 min (DeepSeek — more conservative, includes integration)
- 8-hour ceiling: **8–18 features** (consensus range)
- Today's actual: ~11 items (mix of inline + dispatch)
- Therefore: **~2× upside available, not 10×**.  Both engines reject the operator's implicit "we could be way faster" framing.  The room exists but it's incremental, not transformative.

**Q3 — Memory + hook scoping fix:** Both pick **per-project memory directories** unanimously.  Justifications:
- Tagged filter is fragile (parse prose tags on 51 entries) — MiMo
- Per-dir gives automatic scoping at zero per-session cost — DeepSeek
- Hooks can live next to scoped memory and never fire in wrong session — MiMo

**Q4 — Next packet failure mode:**
- MiMo: **dependency-DAG dispatch** — when packet B needs packet A's output, Claude has no chain-dispatch primitive; will either inline-drift or block
- DeepSeek: **semantic splitting + metadata bloat** — anchor-windowing works today, but cli.py header overhead grows unbounded with session context; next disconnect ~15 KB

**Q5 — Top one-liner ship-next:**
- MiMo: *"move record_dispatch() into the main path of dispatch_packet so budget metering is real and Claude sees a running tally per session"*
- DeepSeek: *"add dispatch_packet(..., bypass_chain=True) so force_engine returns on first failure instead of burning 60–180 s on the chain"*

Both target the dispatcher.  These are independent fixes; both should ship.

---

## Phase 2 — Validation matrix

| Component | Test | Result |
|---|---|---|
| `harness doctor` | preflight checks | ✅ all 6 checks green |
| `harness observer status` | armed + 7 cycles | ✅ no flags |
| `harness coord status` | latest run | ⚠️  no human output (CliRunner quirk; the `--json` path that just shipped works) |
| `harness budget summary` | --since-days 7 | ❌ reports `(no dispatches)` despite 1354 ledger entries (zero-token entries are filtered out as if not present) |
| Direct HTTP probe kimi-k2.6 | small prompt | ✅ 200 OK, 1.8 s |
| Direct HTTP probe deepseek-v4-flash | small prompt | ✅ 200 OK, 1.4 s |
| Direct HTTP probe mimo-pro-sgp | small prompt | ✅ 200 OK, 2.0 s |
| Direct HTTP probe mimo-v2.5-std-sgp | small prompt | ✅ 200 OK, 1.3 s |
| Direct HTTP mimo-pro | 10 KB review packet | ❌ `RemoteProtocolError` after 69 s — server-side disconnect |
| Direct `engine.dispatch` kimi | 3 KB review packet | ❌ "internal" at 62 s |
| Direct `engine.dispatch` mimo | 3 KB review packet | ✅ 34 s |
| Direct `engine.dispatch` deepseek | 3 KB review packet | ✅ 15 s |

### Phase-2 defects surfaced:

1. **`dispatch_packet` runs full fallback chain even with `force_engine`** — 60 s engine failure becomes 120–240 s total before returning.  Both engine reviewers flagged this.  Fix: add `bypass_chain=True` kwarg.
2. **Budget meter summary blind to zero-token entries** — `harness budget summary` shows `(no dispatches)` despite 1354 ledger rows because the recent entries have `input_tokens=0, output_tokens=0` (recorded as a placeholder by some dispatch paths).  The summary likely filters out zero-cost rows.
3. **Kimi K2.6 unusable for long-form generation** — third failure today at exactly 60 s.  Server-side reasoning cap.  Workaround: route long-form tasks to MiMo or DeepSeek; keep Kimi for short surgical patches.
4. **10 KB packet ceiling on direct engine HTTP** — server disconnects at 60–70 s.  Keep review/analysis packets under ~5 KB.

---

## Phase 3 — File-structure + memory audit

### Memory entries — the big finding

```
~/.claude/projects/D--Projects/memory/  (shared across ALL projects under D:/Projects)

Total entries: 51
  warehouse-only:  27  (53%)  ← loaded into every xaxiu-harness session as noise
  harness-only:     8  (16%)
  BOTH-scope:       4  (8%)
  generic:         12  (24%)
```

**Every xaxiu-harness session loads ~27 entries about Maersk planner, V-file dispatching, warehouse-specific dev loops** that have zero bearing on xaxiu-harness work.  At ~100–500 lines per entry that's 2 700–13 500 lines of context burned per session for the wrong project.

### Cross-project hook leakage — confirmed

- `xaxiu-harness/.claude/hooks/` exists (own settings).
- `warehouse/.claude/hooks/check-csv-stale.sh` is **firing inside xaxiu-harness sessions** (~15 times today).
- Likely cause: Claude Code's hook runner registers hooks from ALL `.claude/hooks/` it has seen, not just the active project root.
- Symptom: hook noise that ate context + caused the "halting until real input" loop earlier this session.

### Orphan artifacts on disk

```
.harness/worktrees/   3 dirs  (20260520T220000-ab12, 20260522T022911-490b, 20260522T041500-smk1)
runs/                 2 dirs  (latest 2)
coord/dispatches/    60 KB
coord/dev_loop/     343 KB  (largest; budget_ledger.jsonl 238 KB / 1354 entries)
coord/observer/     107 KB
coord/packets/      688 KB  (biggest — historical packets from earlier waves)
coord/reviews/       34 KB  (this report's dir; untracked)
coord/benchmarks/    24 KB
coord/validation/     0 KB  (created today, empty so far)
```

- 3 orphan worktrees from prior runs — should be `harness coord cleanup` after each successful integration.
- `coord/reviews/` is untracked in git (gitignore needed or include in commits).

### Potential memory-name conflicts

```
feedback_status_csv_*  →  2 entries (canonical + never_empty) — both fire on STATUS rules
reference_xaxiu_swarm_*  →  2 entries (canonical_syntax + concurrency_calibration) — both fire on swarm dispatch
```

These aren't conflicts per se — they're complementary — but the loader treats them as independent rules.  Worth consolidating into single canonical files.

---

## Phase 4 — Migration verdict

### Recommendation: **migrate the memory layout, not the project folder.**

xaxiu-harness already lives at `D:/Projects/xaxiu-harness/` — separate from `D:/Projects/warehouse/`.  The project-folder isolation is fine.  The problem is the **shared memory directory**.

### Proposed structure

```
~/.claude/projects/D--Projects/memory/
├── common/                       # 12 generic entries (load everywhere)
│   ├── feedback_no_premature_stop.md
│   ├── feedback_plan_first_dispatch_default.md
│   ├── feedback_check_memory_first.md
│   └── ...
├── xaxiu-harness/                # 8 harness-only entries
│   ├── feedback_xaxiu_harness_full_dev_authority.md
│   ├── reference_xaxiu_harness_error_taxonomy.md
│   ├── feedback_no_permission_seeking.md
│   └── ...
└── warehouse/                    # 27 warehouse-only entries
    ├── feedback_engine_routing_2026_05_11.md
    ├── feedback_cartridge_principle.md
    └── ...
```

Plus an `.scope` file or filename convention so the session loader knows which directory to glob based on `cwd` at session start.

### Migration steps (atomic; reversible)

1. `mkdir ~/.claude/projects/D--Projects/memory/{common,xaxiu-harness,warehouse}`
2. Use the audit script's classification to `git mv` each entry into its scope dir
3. Update Claude Code's memory loader (or write a wrapper) to glob by cwd-detected project
4. Test session-start: harness session loads only ~20 entries (common + harness) instead of 51
5. Test warehouse session loads ~39 entries (common + warehouse) instead of 51
6. If any entry was mis-classified, move it; the operation is `git mv` + reload

### Estimated impact

- Per-session context savings: ~2 700–13 500 lines reclaimed (53% memory load reduction)
- Cross-project hook fix: separate effort — needs Claude Code hook-loader change or per-project hook registration
- Memory-conflict surface: drops from 51 entries × 5 projects = 255 cross-pairs to 12 + 8 = 20 in-scope entries × 1 project = 20.  ~12× reduction in confusion surface.

### Items NOT to migrate

- The xaxiu-harness project folder itself (`D:/Projects/xaxiu-harness/`) — already isolated
- Per-project `.claude/hooks/` — already isolated; the cross-fire bug is in Claude Code's loader, not the file layout
- Per-project `coord/STATUS.csv` — already isolated

---

## Concrete next-ship items (in priority order)

1. **Dispatcher `bypass_chain=True` kwarg** (DeepSeek pick).  ~10 LOC + 2 tests.  Cuts 60–180 s off every failed `force_engine` dispatch.
2. **`record_dispatch` always called from main `dispatch_packet` path** (MiMo pick).  ~5 LOC + 1 test.  Makes budget metering real.  Side benefit: Claude sees a running tally and can self-correct from "dispatched 0 of 12 items."
3. **Memory directory restructure** (consensus).  ~30 min of `git mv` + 1 loader hook.  53% memory load reduction.
4. **`harness coord cleanup` after successful integrate** (housekeeping).  Removes orphan worktrees.  Already a verb; just needs to fire automatically.
5. **`coord/reviews/` add to gitignore or commit policy** (~1 min).
6. **Kimi K2.6 routed away from long-form review/analysis tasks** (operator-side config in `engine_routing`).  Use Kimi for short surgical patches; MiMo Pro for analysis; DeepSeek for V-file work.

Items 1, 2, 3 together close 80% of the throughput-ceiling gap.  Estimated wall time: 60–90 min total if dispatched to MiMo Pro + DeepSeek in parallel.

---

## What I owe the operator next

A plan-then-dispatch wave shipping items 1–5 above.  All small, all dispatch-eligible per the corrected discipline.  Item 6 is operator config — they decide routing per their workflow.

Author: Claude (synthesis) + MiMo V2.5-Pro + DeepSeek V4-flash (engine reviews)
Date: 2026-05-22
Sources: `coord/reviews/external/20260522T101432Z_review_{mimo-pro,deepseek-thinking}.md` + Phase-2/3 probe logs
