<!-- persona=P4-risk-analyst status=OK (25300ms) -->

# P4-risk-analyst

## 1. Top‑line summary

Wave 11’s agent‑first ambition carries three high‑severity risks: uncontrolled API cost, regression in existing dispatch clients, and operator workspace corruption.  I recommend sequencing the hygiene rows first (to stabilise test baselines), adding a cost‑gating step to budget status, and adopting a “write‑only to new paths” policy for AGENT‑INIT to avoid STATUS.csv collisions.  Any sub‑wave that touches the dispatch path (B, C) should block on a full pass of the existing mutation canary before merging.

---

## 2. Top‑5 risks (ranked by probability × impact)

| # | Risk | What goes wrong | Leading indicator | Mitigation / rollback |
|---|------|----------------|------------------|-----------------------|
| 1 | **API cost creep** | Telemetry (budget_status) and frequent dispatch calls drive subscription engine costs above operator’s tolerance, or cause budget exhaustion mid‑session. | Per‑session API‑call count spikes >20% compared to W10 baseline; cost‑ledger shows `offload_ratio` dropping below 0.7. | Add a `COST_MAX_PER_SESSION` env‑var (default 1000 engine calls).  budget_status() logs a warning when approaching limit.  Rollback: disable telemetry calls in dispatch_packet. |
| 2 | **Context‑preservation refactor breaks existing dispatchers** | Changing DispatchResult default from full payload to summary + content_ref breaks callers that expect `response.text` or `response.json()` immediately. | Any integration test (e.g. `test_dispatch_returns_payload`) fails; mutation canary shows >1 deviation per 100 runs. | Run full mutation canary before merging W11‑CONTEXT‑FRUGAL‑RETURN.  Use feature‑flag (`DISPATCH_FULL_BY_DEFAULT=True`) to keep old behaviour.  Rollback: revert to previous DispatchResult schema. |
| 3 | **Agent‑target‑project conflicts** | `harness agent init` writes a STATUS.csv snippet or .harness/ dir into a target that already has an operator‑owned STATUS.csv, corrupting the project’s state. | Existing `STATUS.csv` or `.harness/` found at target during init; user reports “unexpected rows” in status. | `agent init --force` (default off); if target is a git repo, require clean working tree.  Write STATUS.csv as `_harness_status.csv` initially, then symlink after operator confirmation.  Rollback: `agent init --undo` removes all written files. |
| 4 | **Cross‑platform observer regression** | The cron‑based observer on Linux/macOS fails to handle system sleep/wake, or the Windows Task Scheduler observer has timer drift, causing missed or duplicate dispatches. | Observer logs show intervals >2× configured period; watchdog recovery triggers too often (>1 per 100 cycles). | Ship a health‑check endpoint (observer status / last‑pulse timestamp).  Use `--cron-fallback 60` to re‑sync after sleep.  Rollback: revert to W10 observer (single‑platform Task Scheduler); file a bug for cron. |
| 5 | **Competing‑tools window** | Cursor or Claude Code ship native agent routing (similar to our agent‑first dispatch) in the same 2‑4 week window, reducing adoption incentive for Harness. | Public changelogs / release notes from Anthropic or Cursor mention “agent routing” or “multi‑engine dispatch”. | Accelerate the “adapter‑validate JSON” row (W11‑ADAPTER‑VALIDATE‑JSON) to ship a compelling DX differentiator (structured errors, suggested fixes).  Keep adapter count at ≥5 non‑trivial adapters (GPTResearcher, Perplexity, etc.).  No rollback – only pivot to integration‑first marketing. |

---

## 3. Two open questions for the operator

1. **What is the per‑operator engine call budget?** Without a hard cost limit (e.g. 500 calls per session), telemetry rows risk silent budget exhaustion.  Please define `COST_MAX_PER_SESSION` before shipping W11‑AGENT‑TELEMETRY.

2. **Should `agent init --target <path>` refuse to run if the target is the operator’s own workspace?**  If yes, we can add a `--allow-self` flag.  If no, the STATUS‑collision mitigation becomes critical.  Clarify the use case: initialising adapters for the Harness codebase itself, or exclusively for external projects?

---

## 4. Alignment check (reorder / merge / split)

- **Merge** `W11‑HIDE‑ADVANCED‑VERBS` into the start of Wave 11‑A.  This reduces the surface area while we are most at risk of operator confusion from new verbs.
- **Reorder**: run the three engineering‑hygiene rows (`W11‑AUDIT‑ALL‑W10‑ROWS`, `W11‑MUTATION‑PATTERN‑EXPANSION`, `W11‑PER‑CHECK‑LATENCY`) **before** any sub‑wave.  This hardens the regression detection that the risk analyst relies on.
- **Split** `W11‑CONTEXT‑FRUGAL‑RETURN`: decompose into (1) `DispatchResult` schema change + feature flag, (2) lazy content fetch.  Test (1) alone before enabling (2) to isolate breakage.
- No change to Wave 11‑C ordering; it depends on both A and B being stable.
