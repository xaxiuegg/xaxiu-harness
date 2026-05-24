# W11 execution-planning panel — synthesis

_Dispatched: 5 reviewers, elapsed 59s_

## P1-sequencer  (deepseek/deepseek-v4-flash)

## 1. Top-line summary

Ship **W11‑AGENT‑INIT‑VERB** first — it creates the `.harness/` state directory, `.env`, adapter scaffold, and `STATUS.csv` that every subsequent row depends on. Ship **W11‑PYTHON‑SDK‑API** last — it wraps `dispatch`, `retrieve`, and `budget_status` and must wait for all core internals (frugal return, cache, telemetry) to stabilise. The critical path is `AGENT‑INIT‑VERB → DPAPI‑CROSS‑PLATFORM → CONTEXT‑FRUGAL‑RETURN → DISPATCH‑CACHE → RETRIEVE‑API → AGENT‑TELEMETRY → CROSS‑PLATFORM‑OBSERVER → PYTHON‑SDK‑API`, with engineering‑hygiene rows folded into the slack.

## 2. Concrete artifact

### (a) First row
| Row ID | Reasoning |
|--------|-----------|
| `W11-AGENT-INIT-VERB` | Creates `.harness/` state dir, `.env` file, adapter scaffold, `STATUS.csv`, and `CLAUDE.md` snippet. Every other row reads/writes these structures. No other row can execute without this foundation. |

### (b) Last row
| Row ID | Reasoning |
|--------|-----------|
| `W11-PYTHON-SDK-API` | Public API (`dispatch`, `retrieve`, `budget_status` + type stubs). Depends on `CONTEXT‑FRUGAL‑RETURN`, `DISPATCH‑CACHE`, `RETRIEVE‑API`, and `AGENT‑TELEMETRY` being stable. Also requires the `L5‑OUTPUT‑CONTRACT` to define SDK output shape. Shipping it last minimises API churn. |

### (c) Critical‑path chain
```
W11-AGENT-INIT-VERB
  │
  ├─ W11-DPAPI-CROSS-PLATFORM  (secrets needed for adapter config)
  │
  ├─ W11-CLAUDE-MD-TEMPLATE    (can follow immediately; no further deps)
  │
  └→ W11-CONTEXT-FRUGAL-RETURN  (DispatchResult default shape)
        │
        └→ W11-DISPATCH-CACHE    (uses content/adapter hash, depends on DispatchResult)
              │
              └→ W11-RETRIEVE-API  (needs frugal return + cache)
                    │
                    └→ W11-AGENT-TELEMETRY  (budget_status uses retrieve? no, but depends on record_dispatch)
                          │
                          └→ W11-CROSS-PLATFORM-OBSERVER  (needs dispatch/retrieve; cron alternative)
                                │
                                └→ W11-PYTHON-SDK-API     (final wrapper)
```
*Note: `W11‑ADAPTER‑VALIDATE‑JSON` can be inserted after `AGENT‑INIT‑VERB` (or anytime) — it only depends on adapter loading, not on the dispatch chain. It is **not** on the critical path.*

### (d) Parallelisable rows
| Parallel set | Rows | Rationale |
|--------------|------|-----------|
| **Set 1** (after init) | `W11-DPAPI-CROSS-PLATFORM`, `W11-CLAUDE-MD-TEMPLATE` | No cross‑dependencies; both read `.harness/` and `.env` created by init. |
| **Set 2** (after frugal return) | `W11-DISPATCH-CACHE`, `W11-AGENT-TELEMETRY` (partial) | Cache is independent of telemetry; telemetry only needs `budget.record_dispatch` (already exists). However, telemetry’s `dispatches_fired` field benefits from cache being present — defer telemetry until cache is done for accurate counts. |
| **Set 3** (after retrieve) | `W11-CROSS-PLATFORM-OBSERVER`, `W11-OBSERVER-WATCHDOG-RECOVERY` | Observer depends on retrieve; watchdog is a pure recovery mechanism that can be built alongside observer. |
| **Set 4** (any time) | `W11-HIDE-ADVANCED-VERBS`, `W11-L5-OUTPUT-CONTRACT`, `W11-MUTATION-PATTERN-EXPANSION`, `W11-AUDIT-ALL-W10-ROWS` | No runtime deps; best done in parallel with Set 1/2 to fill slack. `L5` must ship before `PYTHON-SDK-API`. `AUDIT` can run at any point but should be re‑run after the full wave ships. |

### (e) Go/no‑go gates between sub‑waves
| Gate | Condition | Action if blocked |
|------|-----------|-------------------|
| **11‑A → 11‑B** | `W11-AGENT-INIT-VERB` + `W11-DPAPI-CROSS-PLATFORM` + `W11-CLAUDE-MD-TEMPLATE` all ✅ | Block B until A shipped. A is small → ship A in one sprint. |
| **11‑B → 11‑C** | `W11-CONTEXT-FRUGAL-RETURN` + `W11-DISPATCH-CACHE` + `W11-RETRIEVE-API` all ✅ | C (telemetry/observer) uses `retrieve`; shipping C without B would cause missing features. |
| **11‑C → release** | `W11-PYTHON-SDK-API` + all 6 engineering‑hygiene rows ✅ | SDK is the final public contract. Hygiene rows must be done (especially `L5‑OUTPUT‑CONTRACT` and `AUDIT‑ALL‑W10‑ROWS`) to avoid regressions. |

## 3. Two open questions for the operator

1. **Should `W11‑ADAPTER‑VALIDATE‑JSON` be moved from 11‑C to 11‑A?** It only depends on adapter loading (exists now) and has no link to telemetry or observer. Moving it earlier would give validation coverage during the dispatch‑cache buildout. The current placement in 11‑C seems arbitrary.

2. **Do we allow early parallel shipping of `W11‑L5‑OUTPUT‑CONTRACT` with 11‑A?** The contract defines the DispatchResult shape that `CONTEXT‑FRUGAL‑RETURN` will implement. If we define the contract first, we reduce rework. Could we start L5 immediately after init? This is a design‑choice gate.

## 4. Alignment check

**Reorderings suggested:**
- Move `W11-ADAPTER-VALIDATE-JSON` from Wave 11‑C to Wave 11‑A (after init). It improves quality early and has no dependency on B or C.
- Move `W11-L5-OUTPUT-CONTRACT` to immediately after `W11-AGENT-INIT-VERB` (as a design specification). It should be completed **before** `CONTEXT‑FRUGAL‑RETURN` starts, not left to the end.
- Fold `W11-HIDE-ADVANCED-VERBS`, `W11-MUTATION-PATTERN-EXPANSION`, and `W11-AUDIT-ALL-W10-ROWS` into parallel slack during 11‑B buildout. They don’t need a dedicated sub‑wave.
- `W11-OBSERVER-WATCHDOG-RECOVERY` is correctly paired with `CROSS‑PLATFORM‑OBSERVER`; ship as a parallel set after `RETRIEVE‑API` is done.
- `W11-PER-CHECK-LATENCY-OBSERVABILITY` is pure engineering hygiene; it can be queued after `DISPATCH‑CACHE` is stable to measure cache hit latency. Defer to post‑B.

No rows are split or merged. The wave structure (A‑B‑C) is sound, but the engineering‑hygiene rows should be interleaved, not batched as a final cleanup.

---

## P2-dependency-mapper  (deepseek/deepseek-v4-flash)

## Dependency Map for W11 Agent-First Rows

| Row | Depends On | Enables | Shared Write-Set |
|-----|------------|---------|------------------|
| **W11-AGENT-INIT-VERB** | Existing: `scaffold_adapter`, `advisory_lock`, `atomic_write_json` | W11-DPAPI-CROSS-PLATFORM, W11-CLAUDE-MD-TEMPLATE, W11-PYTHON-SDK-API (indirect), W11-DISPATCH-CACHE (uses .harness dir) | `.harness/` state dir, `.env`, `CLAUDE.md`, adapter files |
| **W11-DPAPI-CROSS-PLATFORM** | W11-AGENT-INIT-VERB (needs project root), Existing: `dpapi.encrypt_secret`, `has_secret` | W11-AGENT-TELEMETRY (secrets for budget?) | `.env` (adds secrets section) |
| **W11-CLAUDE-MD-TEMPLATE** | W11-AGENT-INIT-VERB (needs project type detection) | W11-AGENT-INIT-VERB (template selection) | `CLAUDE.md` (template content) |
| **W11-PYTHON-SDK-API** | W11-CONTEXT-FRUGAL-RETURN, W11-AGENT-TELEMETRY, W11-RETRIEVE-API (stubs), Existing: `dispatch_packet`, `budget_status` | Downstream tooling (but not in this list) | Type stubs (`harness/__init__.pyi`) |
| **W11-CONTEXT-FRUGAL-RETURN** | W11-DISPATCH-CACHE (lazy fetch), Existing: `dispatch_packet` | W11-PYTHON-SDK-API, W11-RETRIEVE-API | `harness/engines/result.py` (core class), `.harness/dispatched/` (content refs) |
| **W11-DISPATCH-CACHE** | W11-AGENT-INIT-VERB (`.harness/` dir), Existing: `atomic_write_json`, `advisory_lock` | W11-CONTEXT-FRUGAL-RETURN, W11-RETRIEVE-API | `.harness/dispatched/` (cache files) |
| **W11-RETRIEVE-API** | W11-CONTEXT-FRUGAL-RETURN, W11-DISPATCH-CACHE, Existing: `dispatch_packet` | W11-PYTHON-SDK-API | `harness/retrieve.py` (new module) |
| **W11-AGENT-TELEMETRY** | W11-DPAPI-CROSS-PLATFORM? (offload_ratio?), Existing: `record_dispatch`, engine analytics | W11-PYTHON-SDK-API (budget_status) | `harness/budget/` (possibly updated schema) |
| **W11-CROSS-PLATFORM-OBSERVER** | Existing: observer logic, platform detection | W11-OBSERVER-WATCHDOG-RECOVERY | Observer configuration files (e.g. `.harness/observer.yml`) |
| **W11-ADAPTER-VALIDATE-JSON** | Existing: adapter validation | W11-L5-OUTPUT-CONTRACT (format dependency) | stdout only (no file conflicts) |
| **W11-HIDE-ADVANCED-VERBS** | Existing: CLI argparse | None (decoupling) | CLI help strings |
| **W11-L5-OUTPUT-CONTRACT** | W11-ADAPTER-VALIDATE-JSON (one use case), Existing: CLI output | None directly | Output formatting code |
| **W11-OBSERVER-WATCHDOG-RECOVERY** | W11-CROSS-PLATFORM-OBSERVER | None | Watchdog state files (`.harness/watchdog/`) |
| **W11-PER-CHECK-LATENCY-OBSERVABILITY** | Existing: check infra | None | Metrics files / log |
| **W11-MUTATION-PATTERN-EXPANSION** | Existing: mutation canary | None | Mutation config |
| **W11-AUDIT-ALL-W10-ROWS** | None (independent) | None | N/A (read-only audit) |

### Key Findings

- **Circular dependencies**: None detected. Strong DAG with W11-AGENT-INIT-VERB as root.
- **Hidden ordering**: W11-DPAPI-CROSS-PLATFORM and W11-CLAUDE-MD-TEMPLATE both assume AGENT-INIT-VERB has run. W11-PYTHON-SDK-API must wait for CONTEXT-FRUGAL-RETURN, RETRIEVE-API, and AGENT-TELEMETRY.
- **Serialization bottlenecks**: `.harness/` directory is written by AGENT-INIT-VERB, DISPATCH-CACHE, OBSERVER, and WATCHDOG. Only AGENT-INIT-VERB should be serialized first; others can be parallelized if directory exists.
- **Parallelization candidates**: W11-ADAPTER-VALIDATE-JSON (no file writes) can run any time. W11-AUDIT-ALL-W10-ROWS, W11-HIDE-ADVANCED-VERBS, W11-MUTATION-PATTERN-EXPANSION are independent of new rows.

## Two Open Questions

1. **W11-AGENT-INIT-VERB should be the first shipped row** — does the operator want to deliver it as a minimal working verb before any SDK or telemetry work begins, or do they prefer a parallel start on DPAPI and templates (which would require init to be stubbed)?

2. **W11-PYTHON-SDK-API type stubs will be invalidated if CONTEXT-FRUGAL-RETURN or RETRIEVE-API change return types.** Should the stubs be written last (after those rows stabilize), or is an explicit “stub-as-contract” approach preferred where stubs are written first as a spec?

## Alignment Check

The current wave ordering (A→B→C) is correct for the dependency tree. However, **W11-ADAPTER-VALIDATE-JSON** (Wave 11-C) could be moved to any time since it has no file conflicts and no dependencies on other new rows — moving it earlier would give quick user-visible improvement. Similarly, the six hygiene rows are all independent and could be interleaved with Wave 11-A/B without blocking. **W11-OBSERVER-WATCHDOG-RECOVERY** should not ship before **W11-CROSS-PLATFORM-OBSERVER**, but both are self-contained after AGENT-INIT-VERB. Merge suggestion: combine W11-PYTHON-SDK-API and W11-AGENT-TELEMETRY into a single “SDK surface” row to reduce cross-file coordination.

---

## P3-w11a-scope-concrete  (mimo/mimo-v2.5-pro)

## 1. Top-line summary

`harness agent init --target <path>` must be a zero-interactive, idempotent, sub-3-second bootstrap that gives a fresh Claude Code session an immediate first-dispatch command. The spec below is copy-pasteable into an implementation ticket.

---

## 2. The Concrete Spec

### 2a. CLI Signature

```
harness agent init --target <path> [--project-type <type>] [--adapter-name <name>] [--dry-run] [--non-interactive]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--target` | **yes** | — | Directory to bootstrap. Created if nonexistent. Error if exists and is not a directory. |
| `--project-type` | no | `python` | Template selector. Accepted values: `python`, `node`, `generic`. |
| `--adapter-name` | no | derived from `--target` basename (PascalCase + `Adapter`) | Class name for `adapter.py` |
| `--dry-run` | no | `false` | Print every file path + content to stdout; write nothing. |
| `--non-interactive` | no | `false` | Suppress all prompts; overwrite nothing silently. When `false`, interactive sessions get `[y/N]` prompts on collision. |

### 2b. File Tree Written

Given `harness agent init --target ./my-project` (project-type=python, basename=my-project → `MyProjectAdapter`):

```
my-project/
├── .env
├── .gitignore                    # only if not already present
├── adapter.py
├── CLAUDE.md                     # appended if exists; created if not
└── .harness/
    ├── config.json
    ├── run_count                 # literal integer: 0
    ├── dispatched/               # empty dir; .gitkeep
    │   └── .gitkeep
    └── STATUS.csv                # header row only
```

### 2c. Literal File Contents

**`.env`**
```bash
# harness-agent-secrets  —  never commit this file
HARNESS_OPENAI_API_KEY=
HARNESS_DEEPSEEK_API_KEY=
HARNESS_GEMINI_API_KEY=
# HARNESS_ENCRYPT_WITH_DPAPI=1   # Windows-only: uncomment to store secrets in DPAPI
```

**`.gitignore`** (created only if absent)
```
.env
.harness/
__pycache__/
*.pyc
```

**`adapter.py`**
```python
"""Default adapter for my-project — edit project_name and engines as needed."""

from harness.adapters.scaffold import BaseAdapter

ADAPTER_NAME = "MyProjectAdapter"
PROJECT_NAME = "my-project"

DEFAULT_ENGINES = {
    "openai": {
        "model": "gpt-4o",
        "api_key_env": "HARNESS_OPENAI_API_KEY",
        "max_tokens": 4096,
    },
    "deepseek": {
        "model": "deepseek-chat",
        "api_key_env": "HARNESS_DEEPSEEK_API_KEY",
        "max_tokens": 8192,
    },
}


class MyProjectAdapter(BaseAdapter):
    def resolve_engine(self, request):
        return request.engine or "openai"

    def build_packet(self, request, engine):
        return {
            "model": DEFAULT_ENGINES[engine]["model"],
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": DEFAULT_ENGINES[engine]["max_tokens"],
        }
```

**`CLAUDE.md`** (appended section, only if `[harness:agent-init]` marker absent)
```markdown

---
<!-- harness:agent-init -->
# Harness Agent Instructions

Dispatch work to offload engines:

```bash
harness dispatch --target . --engine openai "your prompt here"
```

Retrieve a full result by ID:

```bash
harness retrieve <dispatch_id> --scope full
```

Check remaining budget:

```bash
harness budget --target . --show
```

> Do NOT edit `.harness/config.json` or `adapter.py` without also updating STATUS.csv history.
```

**`.harness/config.json`**
```json
{
  "adapter_module": "adapter",
  "adapter_class": "MyProjectAdapter",
  "project_name": "my-project",
  "created_at": "<ISO-8601 UTC>",
  "init_version": "w11"
}
```

**`.harness/run_count`**
```
0
```

**`.harness/STATUS.csv`**
```
timestamp,dispatch_id,engine,tokens_used,duration_ms,status,error
```

**`.harness/dispatched/.gitkeep`** — empty file.

### 2d. Idempotency Contract

| Scenario | Behavior |
|---|---|
| Target dir doesn't exist | Create it recursively. |
| `.harness/` missing | Full create. |
| `.harness/config.json` exists | **Error (exit 2)** unless `--non-interactive`. Interactive → `[y/N]` to re-initialize (backs up existing config to `.harness/config.json.bak`). |
| `adapter.py` exists | **Skip with warning** to stderr. Never overwrite. |
| `CLAUDE.md` exists | Scan for `<!-- harness:agent-init -->` marker. If present → **skip**. If absent → **append** section. Never overwrite. |
| `.env` exists | **Skip** silently (operator may have real secrets). |
| `.gitignore` exists | **Skip** silently. |
| `STATUS.csv` exists | **Error (exit 3)** — data file; operator must merge manually. |
| `--dry-run` | Print all paths + contents to stdout. Exit 0. Touch nothing. |

### 2e. Error States

| Condition | Exit Code | Message |
|---|---|---|
| `--target` is not a directory and not creatable | 1 | `ERROR: --target path exists and is not a directory: {path}` |
| Permission denied writing to target | 1 | `ERROR: cannot write to {path}: {os_error}` |
| `config.json` collision, non-interactive | 2 | `ERROR: .harness/config.json already exists. Re-run interactively to overwrite.` |
| `STATUS.csv` collision | 3 | `ERROR: .harness/STATUS.csv already exists and contains dispatch history. Merge manually.` |
| Unknown `--project-type` | 4 | `ERROR: unknown project type '{value}'. Accepted: python, node, generic` |
| `--dry-run` | 0 | Print tree + contents to stdout. |

All warnings go to **stderr**. All file contents in `--dry-run` go to **stdout** (pipe-friendly).

### 2f. Success Message & Teach-Next

On clean exit, print to **stdout**:

```
✓ Initialized harness agent project at {target}/

  Created:
    .env                          ← fill in API keys
    adapter.py                    ← edit engines as needed
    CLAUDE.md                     ← agent instructions (auto-read by Claude Code)
    .harness/config.json          ← project metadata
    .harness/STATUS.csv           ← dispatch ledger

  Next step — dispatch your first packet:

    harness dispatch --target . --engine openai "Summarize the README in 3 sentences"

  Then retrieve the full result:

    harness retrieve <id> --scope full

  Check remaining budget anytime:

    harness budget --target . --show
```

---

## 3. Two Open Questions

1. **Secrets bootstrapping on first dispatch:** If `.env` values are blank at init time, should `harness dispatch` fail fast with `ERROR: HARNESS_OPENAI_API_KEY is empty in .env` (recommended) or fall back to DPAPI/system-env silently? The `.env`-first contract in W11-DPAPI-CROSS-PLATFORM suggests fail-fast, but the spec should state this explicitly.

2. **`adapter.py` vs package:** Should the adapter be a single file (`adapter.py`) or a package (`adapter/__init__.py`)? A single file is simpler for W11, but if multi-file adapters are on the roadmap (e.g., separate `prompts.py`, `parsers.py`), now is the time to decide. Recommendation: ship single-file, document the upgrade path.

---

## 4. Alignment Check

| Action | Details |
|---|---|
| **Split W11-CLAUDE-MD-TEMPLATE out of Wave 11-A** | `agent init` already writes a CLAUDE.md template. Shipping W11-CLAUDE-MD-TEMPLATE separately means two competing templates. Merge it: `init` uses the canonical template, and `CLAUDE-MD-TEMPLATE` becomes the "standalone template library" that `init` imports from. |
| **Reorder: W11-ADAPTER-VALIDATE-JSON before Wave 11-B** | `init` writes `adapter.py` that users will edit. If validation ships after the SDK, agents dispatch broken adapters and get opaque errors. Ship validate+JSON early so `init` can print a "validate your edits" follow-up hint. |
| **W11-HIDE-ADVANCED-VERBS is a prereq** | `harness agent init` surfaces in `--help`. If advanced verbs aren't hidden yet, the help output will be noisy. Ship hide-advanced first or gate `agent` as a hidden subgroup that reveals on first use. |
| **Defer W11-PER-CHECK-LATENCY-OBSERVABILITY** | No dependency on init. Clean it out of the critical path. |

---

## P4-risk-analyst  (deepseek/deepseek-v4-flash)

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

---

## P5-tdd-designer  (mimo/mimo-v2.5-pro)

## TDD Contract Design — W11 Agent-First Rows

### Top-line Summary

All 10 rows need **isolation-first fixtures** that don't touch real engines or DPAPI. Every contract below is achievable with tmp_path, fake adapters, and monkeypatched secrets — no "run real dispatch" dependencies. The implementer should hit green on all fixtures before touching production code. The audit gate should enforce: each row has ≥3 of 5 tests passing, zero XFAIL markers, and no new skip-reason annotations.

---

### Row-by-Row Test Contracts

#### W11-AGENT-INIT-VERB (`harness agent init --target <path>`)

| Aspect | Specification |
|---|---|
| **Fixture** | `tmp_path` with no `.harness/` dir. Mock adapter registry returning one known project type (e.g., "python"). |
| **Must-have tests** | 1. `init --target tmp_path` creates `.env`, `.harness/state/STATUS.csv`, `.harness/dispatched/`, `CLAUDE.md`, adapter scaffold — assert all paths exist. |
| | 2. Idempotent: running init twice does NOT clobber existing `.env` keys — assert `old_key=old_val` survives. |
| | 3. Missing `--target` defaults to cwd — assert `os.getcwd()` fallback works via monkeypatch. |
| | 4. Invalid target path (nonexistent parent) raises `ClickException` with actionable message — assert exit code ≠ 0. |
| | 5. `CLAUDE.md` contains the agent-context snippet (must have the string `## Harness Agent Context`) — assert substring present. |
| **Integration** | Call `init`, then `harness adapter validate --json` (W11-ADAPTER-VALIDATE-JSON) on the scaffold — expect zero errors. Cross-module: proves scaffold is immediately usable. |
| **Audit gate** | All 5 tests pass. `git diff --stat tmp_path` after init matches a deterministic file list (no extra files). |

---

#### W11-DPAPI-CROSS-PLATFORM

| Aspect | Specification |
|---|---|
| **Fixture** | `.env` file with `OPENAI_KEY=env_val_123` at tmp_path. Monkeypatch `harness.secrets.dpapi.has_secret` to return False (non-Windows). Monkeypatch `resolve_keys` to read from tmp_path/.env. |
| **Must-have tests** | 1. `resolve_keys(["OPENAI_KEY"])` returns `{"OPENAI_KEY": "env_val_123"}` when no DPAPI — assert value matches. |
| | 2. `--encrypt-with-dpapi` flag on Windows path: monkeypatch `has_secret → True`, `decrypt_secret → "dpapi_val"`. Assert DPAPI value wins over .env when flag set. |
| | 3. Missing key in both .env and DPAPI raises `KeyNotFoundError` listing the key name — assert exception message contains key name. |
| | 4. `.env` with malformed line (no `=`) is silently skipped — assert other keys still resolve. |
| | 5. Precedence: .env value chosen when `--encrypt-with-dpapi` NOT set, even if DPAPI has it — assert `"env_val"` returned. |
| **Integration** | `harness agent init` (W11-AGENT-INIT-VERB) writes `.env`, then `resolve_keys` reads it back — round-trip test. |
| **Audit gate** | All 5 tests pass. No test touches the Windows registry hive — all DPAPI calls are mocked. `grep -r "ctypes" tests/` returns zero (no real DPAPI in tests). |

---

#### W11-CLAUDE-MD-TEMPLATE

| Aspect | Specification |
|---|---|
| **Fixture** | Two template files in `harness/templates/`: `python.md`, `generic.md`. Each ≤800 chars. |
| **Must-have tests** | 1. `render_template("python", project_name="myproj")` contains `myproj` and `python`-specific guidance — assert substring. |
| | 2. Unknown project type falls back to `generic.md` — assert no KeyError, generic content returned. |
| | 3. Rendered output is ≤800 chars — `assert len(output) <= 800`. |
| | 4. Template is valid UTF-8 and contains no placeholder tokens (`{{` or `{%`) — assert absence. |
| **Integration** | `harness agent init --type python` (W11-AGENT-INIT-VERB) writes rendered template to `CLAUDE.md` — assert file content matches `render_template("python")`. |
| **Audit gate** | 4 tests pass. All template files pass `wc -c < 800`. |

---

#### W11-PYTHON-SDK-API

| Aspect | Specification |
|---|---|
| **Fixture** | `import harness` is importable. Minimal adapter registered via monkeypatch returning canned response. |
| **Must-have tests** | 1. `from harness import dispatch, retrieve, budget_status` succeeds — assert no `ImportError`. |
| | 2. `dispatch("test prompt")` returns `DispatchResult` with `.summary`, `.metadata`, `.content_ref` attributes — assert all `hasattr`. |
| | 3. `retrieve("fake_id", scope="summary")` calls internal retrieval with correct args — assert via mock spy. |
| | 4. `budget_status()` returns dict with expected keys — assert `isinstance(result, dict)` and keys present. |
| | 5. Type stubs exist: `harness/__init__.pyi` has `dispatch` signature — assert file exists and contains `def dispatch(`. |
| **Integration** | Import the SDK in a subprocess (`python -c "from harness import dispatch"`) — proves no circular imports at module level. |
| **Audit gate** | `mypy harness --strict` passes with zero errors on the public API surface. All 5 tests green. |

---

#### W11-CONTEXT-FRUGAL-RETURN

| Aspect | Specification |
|---|---|
| **Fixture** | Fake engine adapter returning payload with `content` (5000 chars), `metadata` dict, `cost`. |
| **Must-have tests** | 1. `DispatchResult` default attributes: `.summary` is non-empty string ≤200 chars, `.metadata` is dict, `.content_ref` is string (not full content) — assert all. |
| | 2. `.full()` returns the complete content — `assert len(result.full()) == 5000`. Called twice, fetches once (spy on internal loader). |
| | 3. `error_excerpt` present on error results: simulate adapter raising `EngineError` — assert `.error_excerpt` is first 200 chars of traceback. |
| | 4. Tail preservation: last 50 chars of response survive in `.summary` when content ends with key conclusion — assert `content[-50:]` substring in summary or metadata. |
| | 5. No raw content in default serialization: `json.dumps(result)` excludes `.full()` content — assert `"full_content"` not in serialized string. |
| **Integration** | SDK `dispatch()` (W11-PYTHON-SDK-API) returns `DispatchResult` — assert same class, same contract. Cross-row dependency: W11-PYTHON-SDK-API must land first or in same PR. |
| **Audit gate** | All 5 tests green. Memory profile: `tracemalloc` shows `.summary` path allocates <10% of `.full()` path for 50KB payload. |

---

#### W11-DISPATCH-CACHE

| Aspect | Specification |
|---|---|
| **Fixture** | tmp_path with `.harness/dispatched/` dir. Mock engine returning deterministic content for same input. |
| **Must-have tests** | 1. Two identical `dispatch()` calls return same result, engine called once — assert engine mock call count == 1. |
| | 2. Changed prompt content produces cache miss — assert engine called twice for two different prompts. |
| | 3. Changed adapter version (hash) produces cache miss even for same prompt — assert engine called twice. |
| | 4. Cache file is valid JSON on disk in `.harness/dispatched/` — assert `json.load()` succeeds. |
| | 5. `--no-cache` flag bypasses cache — assert engine called even for repeated prompt. |
| **Integration** | `dispatch()` via SDK (W11-PYTHON-SDK-API) + cache hit → `DispatchResult` loads from cache — assert correct type returned. |
| **Audit gate** | All 5 tests green. Cache dir contains ≤2 files per unique (content_hash, adapter_hash) pair. |

---

#### W11-RETRIEVE-API

| Aspect | Specification |
|---|---|
| **Fixture** | Pre-written result file in `.harness/dispatched/{id}.json` with full payload. |
| **Must-have tests** | 1. `retrieve(id, scope="summary")` returns short dict without full content — assert len < 10% of full. |
| | 2. `retrieve(id, scope="full")` returns complete payload — assert all fields present. |
| | 3. `retrieve(id, scope="chunks")` returns list of ≤N chunk dicts — assert `isinstance(result, list)`. |
| | 4. Nonexistent id raises `ResultNotFoundError` — assert exception with id in message. |
| | 5. Corrupted file on disk returns `ResultCorruptedError` — write garbage bytes, assert graceful failure. |
| **Integration** | `dispatch()` returns `content_ref` → `retrieve(content_ref, scope="full")` returns same data — round-trip. Depends on W11-CONTEXT-FRUGAL-RETURN + W11-DISPATCH-CACHE. |
| **Audit gate** | All 5 tests green. Retrieve latency for summary scope < 5ms (assert via `time.monotonic()` delta). |

---

#### W11-AGENT-TELEMETRY

| Aspect | Specification |
|---|---|
| **Fixture** | `budget.record_dispatch` called 3 times with different engines and costs. |
| **Must-have tests** | 1. `budget_status()` returns dict with keys: `offload_ratio`, `remaining_budget`, `dispatches_fired`, `engines_used` — assert all keys present. |
| | 2. `engines_used` is `dict[str, int]` mapping engine name → count — assert types. |
| | 3. `remaining_budget` decreases after a dispatch — assert `before > after`. |
| | 4. `offload_ratio` is float in [0.0, 1.0] — assert bounds. |
| | 5. Empty state (no dispatches) returns zeros, not crash — assert `dispatches_fired == 0`. |
| **Integration** | SDK `budget_status()` (W11-PYTHON-SDK-API) returns same data — same function. |
| **Audit gate** | All 5 tests green. `budget_status()` completes in < 10ms. |

---

#### W11-CROSS-PLATFORM-OBSERVER

| Aspect | Specification |
|---|---|
| **Fixture** | Mock observer cycle function. tmp_path with mock cron file output. |
| **Must-have tests** | 1. `generate_cron_entry()` returns valid crontab string with correct interval — assert regex match `^(\S+\s){5}`. |
| | 2. Cron entry contains absolute path to `harness` CLI — assert no relative path. |
| | 3. On Windows: falls back to Task Scheduler XML generation — assert file written. |
| | 4. `--install` flag writes cron file and prints instructions — capture stdout, assert `crontab` substring. |
| | 5. `--uninstall` flag removes cron entry — assert file cleanup. |
| **Integration** | Observer cycle invoked via cron entry runs `harness observer cycle` — subprocess test with `--dry-run` flag. |
| **Audit gate** | All 5 tests green. Generated cron syntax passes `crontab -l` parse on Linux CI (skip on Windows CI). |

---

#### W11-ADAPTER-VALIDATE-JSON

| Aspect | Specification |
|---|---|
| **Fixture** | Three adapter files: valid, missing-required-field, malformed-syntax. |
| **Must-have tests** | 1. Valid adapter → `validate --json` returns `{"errors": [], "status": "ok"}` — assert `len(errors) == 0`. |
| | 2. Missing field → error object has `field`, `line`, `severity`, `message`, `suggested_fix` keys — assert all keys present. |
| | 3. `severity` is one of `"error"`, `"warning"` — assert value in set. |
| | 4. Malformed Python → `line` points to actual error line — assert `line > 0`. |
| | 5. Exit code 0 for valid, 1 for errors — assert via subprocess return code. |
| **Integration** | `harness agent init` (W11-AGENT-INIT-VERB) scaffolded adapter passes `validate --json` — end-to-end bootstrap validation. |
| **Audit gate** | All 5 tests green. JSON output is valid per `json.loads` — no trailing commas or control chars. |

---

### Two Open Questions

1. **W11-DISPATCH-CACHE and W11-CONTEXT-FRUGAL-RETURN are tightly coupled** — should they land in one PR (single cache key includes content_ref) or does the operator want the cache to store the *full* payload (making .full() a no-op on cache hit)? This changes the cache schema and test #5 on CONTEXT-FRUGAL-RETURN.

2. **W11-CROSS-PLATFORM-OBSERVER cron test** — the test assumes a Linux CI runner for syntax validation. Does the operator have a Windows CI lane, or should the Windows branch be XFAIL-gated with a skip reason?

### Alignment Check

- **Reorder**: W11-PYTHON-SDK-API should land before W11-CONTEXT-FRUGAL-RETURN and W11-RETRIEVE-API — the other three Wave 11-B rows import from it. Currently they're same wave but no explicit dependency chain.
- **Merge**: W11-AGENT-TELEMETRY has only SDK surface; merge its public API test into W11-PYTHON-SDK-API's test file to avoid a stub-only test module.
- **Split**: W11-DPAPI-CROSS-PLATFORM has two distinct behaviors (`.env` reading + DPAPI opt-in). Split the `.env` reader into its own internal module with 3 tests, keeping the DPAPI flag logic separate — the current row conflates platform-detection with config-resolution.

---
