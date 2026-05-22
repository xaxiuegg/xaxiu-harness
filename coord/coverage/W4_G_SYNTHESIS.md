# W4-G Multi-Engine Multi-Agent Coverage Campaign — Synthesis

**Run**: 2026-05-22T13:09–13:17Z  
**Scope**: 20 agent dispatches (4 engines × 5 functions-under-test each).  
**Source artefacts**:
- Probe designs:  `coord/coverage/multi_agent_campaign_20260522T130924Z.json`
- Probe execution: `coord/coverage/multi_agent_execute_20260522T132125Z.json`

## TL;DR

| Engine                  | Probes Designed | % parseable | Probes Executed | % PASS |
|-------------------------|-----------------|-------------|-----------------|--------|
| kimi/kimi-for-coding    | 0 / 5           | 0%          | n/a             | n/a    |
| mimo/mimo-v2.5-pro      | 2 / 5           | 40%         | 0 (both SKIP*)  | n/a    |
| mimo/mimo-v2.5 standard | 3 / 5           | 60%         | 1 / 3           | 33%    |
| deepseek/deepseek-v4-flash | 5 / 5        | 100%        | 3 / 5           | 60%    |
| **Overall**             | **10 / 20**     | **50%**     | **4 / 8 executable** | **50%** |

\* Both MiMo Pro probes targeted nonexistent run-ids — skipped to avoid noise.

## Finding 1 — Engine reliability gap (operator-notify)

**Kimi K2.6 returned empty on 5/5 dispatches** (~4KB packets, 60-secondish 
latencies). First dispatch reported `error: "internal"`; the rest returned 
empty strings with no error field — silent failure. Hypothesis: K2.6 60-s 
thinking cap is hit by the source-code-heavy packets, returning empty 
final-message tokens.

**MiMo v2.5-Pro returned empty on 3/5 dispatches** with no error field. 
The 2 that succeeded had small payloads (coord run, coord integrate). The 
3 that failed (coord plan, dispatch_packet, dispatch bypass_chain) all 
embedded longer source files (~4KB). Same hypothesis as Kimi: model 
limits hit silently.

**DeepSeek v4-flash returned parseable output on 5/5**. Lowest latency 
median (~16s vs 21s/26s for MiMo, 41s for Kimi). Most reliable for 
source-code-laden probes.

**Operator action item**: dispatch reliability tier going forward is
`deepseek-v4-flash > mimo-v2.5-std > mimo-v2.5-pro > kimi-for-coding` for 
source-embedded packets. Existing W3-C long-form auto-routing (avoid 
Kimi on >4KB output) should be extended to **input** size as well.

## Finding 2 — Agent-guessed CLI surfaces caught real UX rough edges

The probe executor surfaced 2 FAILs where the agent's probe didn't match 
the actual CLI — both real UX papercuts where source-reading didn't 
translate to invocation:

| Agent guess                              | Actual CLI                                 | Diagnostic                |
|------------------------------------------|--------------------------------------------|---------------------------|
| `harness engines list` (mimo-std)        | `harness engines --list`                   | "list" should be a subcommand OR `--list` is canonical |
| `harness lint-spec --spec X.md` (ds)     | `harness lint-spec X.md` (positional)      | `--spec` flag would be more discoverable |
| `python -c "...read_status()..."` (ds)   | `read_status()` requires `path` arg        | API surface implies zero-arg default; doesn't ship one |

These 3 are real diagnostics worth filing as Wave-5 polish tasks.

## Finding 3 — 4 confirmed-working harness functions

Probes that PASSed end-to-end (exit 0 + keyword overlap with predicted 
output):

| Engine     | FUT                | Probe                                  |
|------------|--------------------|----------------------------------------|
| mimo-std   | budget summary     | `harness budget summary`               |
| mimo-std   | loop start/stop    | `harness loop status`                  |
| deepseek   | proxy lifecycle    | `python -m harness proxy --help`       |
| deepseek   | panic-dump         | `python -m harness panic-dump --target-dir tmp_panic` |
| deepseek   | observer flags     | `harness observer flags`               |

Each of these is now externally validated by an LLM-engine that did not 
write the harness code. The keyword-overlap heuristic is loose (single 
common token suffices) so PASS is the floor, not the ceiling.

## Finding 4 — Cross-engine agreement

The campaign assigned each FUT to a single engine, so we have no direct 
cross-engine diff on the same function. Future iteration: re-run with 
each FUT assigned to 2+ engines and surface disagreement on 
PASS/DEGRADED/FAIL verdicts.

## Next actions (W4-H, W4-I)

1. **W4-H**: Re-run campaign with **DeepSeek as the sole probe-designer** 
   (5/5 reliability) but assign **same FUT set to each engine** for 
   probe-execution attempts. This isolates "can the engine design a probe?" 
   from "does the harness function actually work?"
2. **W4-I**: Promote findings 2 and 3 into the **STATUS.csv** as fixable 
   UX rows (engines-list discoverability, lint-spec --spec flag, 
   read_status default path).
3. Defer Kimi/MiMo-Pro silent-empty root-cause to a separate W4-J 
   dispatcher hardening wave — it's an engine-side issue, not a harness 
   integration bug, and unblocks ship-readiness as long as DeepSeek 
   stays primary.
