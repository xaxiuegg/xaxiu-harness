# Migration to standalone project folder — 2026-05-22

xaxiu-harness was migrated **out of** `D:/Projects/xaxiu-harness/` to its own
standalone parent at `D:/xaxiu-harness-standalone/` so it gets its own
Claude Code project directory (`~/.claude/projects/D--xaxiu-harness-standalone/`)
with isolated memory + isolated hook scope.

Old location (`D:/Projects/xaxiu-harness/`) is **retained as a backup** until
the operator confirms the new location works end-to-end and is the
canonical place to develop xaxiu-harness from going forward.

---

## What moved

### Git tree (full history)

```bash
git clone --local --no-hardlinks D:/Projects/xaxiu-harness D:/xaxiu-harness-standalone
git -C D:/xaxiu-harness-standalone remote set-url origin https://github.com/xaxiuegg/xaxiu-harness.git
```

Origin is the same GitHub repo.  Either location can push.  Operator's
GitHub credentials persist via Windows Credential Manager.

### Operational state (gitignored, manually copied)

```
state/secrets.dpapi               (encrypted; DPAPI is Windows-user-bound, not path-bound — decrypts fine here)
state/active_dispatches.json
state/engine_health.json
state/engine_performance_log.jsonl
state/history.db                  (~238 KB SQLite — dispatch history)
coord/dev_loop/budget_ledger.jsonl  (1 354 entries / ~246 KB)
coord/dev_loop/budget_cap.json
coord/dev_loop/heartbeat.json
coord/dev_loop/log.jsonl
coord/dev_loop/state.json
coord/observer/                   (full dir — armed state, prior cycles)
```

### Memory entries (43 of 51 carried)

| Source | Target | Count |
|---|---|---|
| `~/.claude/projects/D--Projects/memory/` | `~/.claude/projects/D--xaxiu-harness-standalone/memory/` | 43 |

Carried:
- 24 explicitly harness-relevant or generic (first-pass classifier)
- 19 additional generic-discipline entries that mention warehouse only as canonical example (second-pass curated list)
- `MEMORY.md` index file

**Left behind at old location** (8 truly warehouse-specific entries that don't apply to harness):
- `feedback_active_tracking_table` (warehouse STATUS-table specific)
- `feedback_brace_check_per_5_edits` (HTML/JSX editing)
- `feedback_cartridge_principle` (V-file cartridges)
- `feedback_delegate_vfile_to_deepseek` (V-file routing)
- `feedback_operator_customization_first_class` (warehouse data model)
- `project_phase_plan_2026_05_11` (V185.18 phase plan)
- `project_v185_18_architectural_concerns` (V185 spec)
- `user_satisfactory_ux_aspiration` (warehouse planner UX vision)

If any of these were mis-classified and are needed for harness work, copy
them from `~/.claude/projects/D--Projects/memory/` on demand.

### Skipped intentionally (regenerable or orphan)

```
.harness/worktrees/   (3 orphan worktrees from prior runs at old loc)
runs/                 (historical dispatch run dirs; not needed for new development)
__pycache__/          (regenerable)
.pytest_cache/        (regenerable)
.venv/                (re-create via uv if needed; system Python works)
```

---

## What DID NOT move

- The xaxiu-harness git remote (`origin` still GitHub)
- Windows Task Scheduler entries (still registered at old paths — see below)
- Environment variables (`KIMI_API_KEY`, `DEEPSEEK_API_KEY`, `MIMO_API_KEY`) — user-scope persist
- Other projects under `D:/Projects/` (warehouse, etc.) — untouched

---

## Verification at new location (2026-05-22 post-migration)

```
harness doctor          → all 6 checks green
                        → secrets row sees env KIMI/DEEPSEEK/MIMO keys
                        → engine_reachability: mimo=tokenplan (SGP)

pytest                  → 1 224 / 1 224 green (139 s)
```

Fixed during migration: `tests/test_coord_coordinator.py` had 2 tests that
relied on **state pollution at the old location** — they patched
`subprocess.Popen` but not `create_worktree`, so they only passed when a
pre-existing worktree dir made `create_worktree` short-circuit early.
The migration exposed this latent bug; both tests now mock
`create_worktree` properly.

---

## Operator follow-ups before the old location can be deleted

1. **Re-register Windows Task Scheduler entries** pointing at the new path.
   The 3 active observer tasks (`XaxiuHarnessObserverCycle`,
   `XaxiuHarnessObserverChatAudit`, `XaxiuHarnessObserverDailyRetro`)
   and `XaxiuHarnessLoopTick` currently fire against
   `D:\Projects\xaxiu-harness\`.  Either:
   - Run `harness observer install-scheduler --all` from
     `D:\xaxiu-harness-standalone\` (will register new tasks)
   - Then `harness observer uninstall-scheduler` from the old location
     (removes the old-pointer tasks)

2. **Verify a real engine dispatch from the new location**.  Suggested:
   `harness coord plan --spec spec/samples/wave1-doctor-no-engine-warn.md`
   should succeed and write a plan.json under `runs/`.

3. **Push a commit from the new location** to confirm git auth works:
   ```
   cd D:\xaxiu-harness-standalone
   touch coord/migration_smoke.txt && git add -A && git commit -m "smoke: migration commit from new loc" && git push
   ```

4. **Decide on old-location cleanup.**  Once steps 1–3 above are green:
   ```
   # Option A: archive (recommended)
   move D:\Projects\xaxiu-harness D:\Projects\xaxiu-harness.archived-2026-05-22

   # Option B: delete
   Remove-Item -Recurse -Force D:\Projects\xaxiu-harness
   ```

5. **Optional: clean the shared memory dir** of the harness-only entries
   that now also live at the new location.  Decide based on whether you
   still want them available when you cd into the old archived path:
   ```
   # If you keep old as archive, leave the 24 carried entries in both
   # places (harmless duplication).
   # If you delete old, you can leave them in the shared memory dir as a
   # fallback OR remove them.
   ```

---

## Rollback (if anything breaks)

The migration is **non-destructive at the source.**  To roll back:

```
cd D:\Projects\xaxiu-harness  # old location is unchanged
PYTHONPATH=src python -m pytest tests/ -q  # should still be 1224/1224
```

Then delete the new location:

```
Remove-Item -Recurse -Force D:\xaxiu-harness-standalone
Remove-Item -Recurse -Force ~\.claude\projects\D--xaxiu-harness-standalone
```

No data is lost; the old location was a verbatim source.
