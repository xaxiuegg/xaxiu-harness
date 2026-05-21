# PACKET-TEMPLATE-FANOUT-RULE — documented auto-fanout rule for >500 LOC / >2 symbol packets

## Goal

Two recent waves (supervisors-coverage, V2-FIRST-RUN) needed 2-3 retries
because a single packet bundled too much surface area for one Kimi worker
to land cleanly.  This wave codifies an explicit auto-fanout rule in
`coord/dev_loop/dispatch-rules.md` and adds a matching scope-checklist
section to the packet template so future packets are split BEFORE
dispatch instead of being retried after timeout.

This is documentation-only — no code changes, no tests.

## Scope (kimi-api with FIND/REPLACE blocks)

### 1. New auto-fanout rule in `coord/dev_loop/dispatch-rules.md`

Find this anchor (currently around the engine-slots table):

```markdown
After supervisors return diffs in a tick, the manager runs slot-fill (see `coord/dev_loop/manager.md` slot-filling section):
```

Insert a NEW section IMMEDIATELY BEFORE it:

```markdown
## Auto-fanout — split before dispatch (2026-05-21)

A packet is a single Kimi worker's contract.  When the contract is too
broad, the worker times out, returns truncated edits, or silently drops
symbols.  Empirical rate from 2026-05-21 telemetry: supervisors-coverage
needed 3 retries (761df48 / 5a77137 / 3b4ab7b), V2-FIRST-RUN caught 4
gaps that should have been separate scoped waves.

**Hard rule** — split the packet into N siblings dispatched via
`xaxiu-swarm swarm --max-concurrent N` when ANY of the following is true:

| Signal | Threshold |
|---|---|
| Expected edited LOC (counting new files) | > 500 |
| Distinct top-level symbols (`def` / `class` count) | > 2 |
| Distinct top-level files touched (excluding tests) | > 3 |
| Test files added | > 1 |

**Soft rule** — consider splitting also when:
- The packet spans more than one module directory.
- The packet asks for both a schema change AND a wiring change.
- The packet would touch `src/harness/cli.py` (conflict hotspot — see
  `CLI-DECOMPOSE` row in STATUS.csv).

Splitting beats retrying.  3 narrow packets run in parallel beat 1 wide
packet that times out at 420s.

```

### 2. Scope-checklist section in the packet template

Find or create `coord/packets/_template/packet.md`.  If it doesn't exist,
SKIP this step (the rule docs are sufficient).  Otherwise insert the
following near the top, under the existing `## Scope` heading:

```markdown
### Scope checklist (auto-fanout gate)

Before dispatching this packet, confirm:

- [ ] Expected edited LOC ≤ 500 (counting new files)
- [ ] Distinct top-level symbols ≤ 2
- [ ] Top-level files touched ≤ 3 (excluding tests)
- [ ] New test files ≤ 1
- [ ] Touches at most one of (cli.py / planner.py / dispatcher.py)

If any box is unchecked, SPLIT into siblings and dispatch via
`xaxiu-swarm swarm --max-concurrent N`.  See
`coord/dev_loop/dispatch-rules.md` § Auto-fanout.
```

## Acceptance

- `coord/dev_loop/dispatch-rules.md` contains the new `## Auto-fanout` section.
- If a template existed, it contains the new scope-checklist section.
- `python -m pytest --tb=short -q` — overall suite stays green (this is
  docs-only so no tests should change behavior).

## Constraints

- DO NOT touch any `.py` files.
- DO NOT modify other markdown files.
- Keep the new dispatch-rules section under 30 lines.

## Engine guidance

Pure docs edit.  swarm/kimi-api (non-agentic, FIND/REPLACE) is the right
backend.  Timeout 420s.
