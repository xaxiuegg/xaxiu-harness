<!-- name=K1-operator-ux latency_ms=52859 error='' -->

1. **W8-STOP-HOOK-BATCH** — modify `.harness/stop-hook.sh` to (a) ignore `mtime` drift under `mutation/` working directories and (b) emit one batched `STATUS.csv` warning at wave end instead of per-file fires. Reasoning: W7 burned ~6 operator turns on ack-and-touch loops that contained zero decision value; the hook is crying wolf and the operator is acting as a human cron job.

2. **Preserve:** The Phase B panel-closeout composite. The operator honestly translated a 4/6 split into a conditional accept plus a backlog-locked W7 worker without gaming the gate. Codify this as a `panel-synthesis.md` template so the pattern survives session handoffs.

**Replace:** Audit-script semantic STOPs. In W6, the auditor expected behavioral integration but received unit + sentinel coverage, forcing the operator to manually interpret and reroute. Add a structured `audit-scope` field (e.g., `[unit|integration|sentinel]`) to each gate so mismatches auto-open a pre-filled remediation branch instead of halting with an opaque STOP.

3. **Theme: Eradicate operator toil loops.** The next waves should (a) finish the stop-hook silence work, (b) block wave close when worktree branches contain unmerged files like `transport.py` (W6-B1 partial), and (c) harden the engine-transport ABC so MiMo batch-HTTP drops are caught at dispatch, not silently excluded. The operator should review outcomes, not nurse diffs through gates.
