# W4-L: End-to-end coord pipeline validation with all W4 guards live

**Run**: 2026-05-22T14:04Z–14:08Z  
**Spec**: `spec/samples/hello-world.md`  
**Engine**: `swarm/mock` (Mock produced no FILE/REPLACE — by design, to
prove the guards fire on degenerate input)

## What this proves

The harness now **refuses to claim success on a silent failure**.
Pre-W4-A/B, a worker that produced 0 file edits would have written
`state=completed` and the integrator would have returned
`success=True, commit=None`.  The operator's overnight run would have
"shipped" without anything actually landing.

## Pipeline tick-by-tick

### Tick 1 — `coord plan`
```
$ python -m harness coord plan --spec spec/samples/hello-world.md --engine mock
plan: runs\20260522T140437-3622\plan.json
```
Generated WavePlan with worker-1 / write_set=['mock-out-1.txt'].

### Tick 2 — `coord run` (PLANNING → RUNNING)
```
$ python -m harness coord run --spec ... --run-id 20260522T140437-3622 --engine swarm/mock --proxy off
run 20260522T140437-3622: running
```
State machine transitioned PLANNING → RUNNING; no workers launched yet
(by design — second tick launches).

### Tick 3 — `coord run --resume` (RUNNING → workers spawned)
Worker-1 subprocess detached, ran through `harness coord work`, dispatched
to swarm/mock.  Swarm/mock returned `success=False, text=""`.  Worker hit
the W4-A no-op detect on step `s1` (kind=edit, target_files=['mock-out-1.txt'],
files_modified=[]).

Result (`runs/20260522T140437-3622/checkpoints/worker-1.json`):
```json
{
  "worker_id": "worker-1",
  "state": "failed",
  "files_modified": [],
  "tests_summary": "silent_no_op:s1",
  "commit_sha": null
}
```

Error sidecar (`worker-1.error.json`):
```json
{
  "error_tag": "L3.dispatch.E_SILENT_NO_OP",
  "diagnostic": "silent_no_op: step s1 declared target_files=['mock-out-1.txt']
                 but 0 files were modified.  Engine likely returned non-matching
                 anchors or no FILE/REPLACE blocks.
                 result.success=False, text_len=0."
}
```

Progress log (`worker-1.progress.jsonl`) tracked both `step_start` and
`worker_failed` events — full diagnostic trail.

### Tick 4 — `integrate`
```python
>>> integrate(run_dir=Path('runs/20260522T140437-3622'),
              project_root=Path('.'), merge_workers=True)
IntegrationReport(
    success=False,
    workers_merged=[],
    workers_skipped=['worker-1'],
    workers_conflicted=[],
    diagnostic="silent_no_op: 0 workers committed (no merge candidates, no
                conflicts). ... skipped=['worker-1']."
)
```
**W4-B fired.**  The integrator did NOT pretend success.  No git
operations attempted.

## What this means for unattended overnight shipping

The harness now has **two independent guards** for the silent-failure
case, which was the #1 hidden risk for unattended overnights:

| Guard | Layer | Behaviour |
|-------|-------|-----------|
| W4-A  | Worker | `edit` step with `target_files` but `files_modified=[]` → `state=failed`, `L3.dispatch.E_SILENT_NO_OP` |
| W4-B  | Integrator | 0 merged workers + 0 conflicts → `success=False` with `silent_no_op:` diagnostic |

Together with the existing engine-side guards:

| Guard | Engine | Behaviour |
|-------|--------|-----------|
| Rule 1 | DeepSeek v4-flash | Re-labels JSON-tool-call leakage as `packet_trap` |
| Rule 2 | Kimi | Re-labels empty/XML-preamble as `kimi_empty_or_xml` |
| Rule 3 | Anthropic | Re-labels refusal text as `anthropic_refusal` |
| Rule 4 (W4-J) | MiMo | Re-labels success+empty as `mimo_empty` |

…the dispatcher always falls back, and the worker/integrator always
refuse silent success.  The overnight session can't drift into
"shipped nothing but claimed yes" territory.

## Next operator-visible signals

1. **Engine reliability** (W4-G): DeepSeek 5/5 reliable; Kimi 0/5 silent
   empty on >4KB packets; MiMo Pro 2/5 reliable.  Production default
   = DeepSeek v4-flash; auto-route avoids Kimi on long form (W3-C).
2. **Token tracking** (W4-K): every dispatch now records real tokens_in/out
   in the budget ledger.  Cost reporting is finally accurate.
3. **UX papercuts** (W4-H): external agents can now invoke common
   commands with their best-guess syntax.

The harness is ready for unattended overnight shipping with DeepSeek as
the primary engine.
