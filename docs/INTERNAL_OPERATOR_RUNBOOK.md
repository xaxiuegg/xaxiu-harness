# Internal Operator Runbook

**Audience**: the operator + any future Claude session that picks up
this project.  Captures the load-bearing operational knowledge that
would otherwise live only in chat history.

**Last updated**: 2026-05-25 (Wave 13 — Operations Foundation)
**Project version**: v1.0.0-rc.1+

---

## Quick reference

```bash
# Daily use
harness today                              # what shipped + open blockers + L5 events
harness cost-today                         # spend vs $5/session cap
harness review <file>                      # 3-engine review of any doc/code
harness observer watchdog-status           # is the observer actually running?

# Emergency
harness preflight --fix --dry-run          # preview auto-remediation
harness observer restart                   # re-arm the scheduler
bash scripts/v1-rc1-24h-report.sh         # day-of-use wake-up report
```

---

## Section 1: When your laptop dies

### 1a. Restore from backup (when W13-BACKUP-RESTORE ships)

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
pip install -e .

# Restore the runtime state (last backup):
harness restore <path-to-latest-backup-archive>
# This restores: .harness/dispatched/ (cache), coord/observer/ (state),
# coord/STATUS.csv (task tracker), and the dispatch budget ledger.

# Verify:
harness preflight --skip-engines           # should be PASS-WITH-WARNINGS
harness observer watchdog-status           # should be UNINITIALIZED (fresh)
harness observer install-scheduler         # re-arm cron / Task Scheduler
```

### 1b. If no backup exists (or W13-BACKUP-RESTORE hasn't shipped)

Everything important EXCEPT runtime state is in git.  You lose:
- The dispatch cache (`.harness/dispatched/`) — affects `harness retrieve` for past dispatches
- Cumulative cost ledger — `harness cost-today` shows $0 again
- Observer cycle history

Recovery:
```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
pip install -e .
# Set keys:
cp .env.example .env  # if exists; otherwise create
# Add KIMI_API_KEY, DEEPSEEK_API_KEY, MIMO_API_KEY

# Verify:
harness preflight
harness review some-test-doc.md            # smoke test
```

---

## Section 2: When an API key needs rotating

### 2a. After W13-SECRETS-ROTATION ships (Wave 13)

```bash
harness secrets rotate kimi
# Walks you through: get new key from platform.moonshot.cn,
# updates .env, updates DPAPI on Windows, tests connectivity,
# reverts if test fails.
```

### 2b. Today (manual)

```bash
# 1. Get the new key from the engine's platform UI
# 2. Update the .env file:
#    KIMI_API_KEY=sk-...
# 3. (Windows) Update DPAPI cache:
PYTHONPATH=src python -c "from harness.secrets.dpapi import store_secret; store_secret('KIMI_API_KEY', 'sk-NEW-KEY')"
# 4. Test:
PYTHONPATH=src python -c "import harness; r = harness.dispatch('reply OK', engine='kimi'); print(r.success, r.error_excerpt)"
# 5. If test fails, revert the .env / DPAPI to the old key
```

---

## Section 3: When an engine goes down

The harness has automatic recovery — circuit breakers + cooldowns
should handle most transient failures.  What to do for persistent
ones:

### 3a. Check what the harness thinks

```bash
harness preflight                          # exercises each engine
harness engines reliability                # historical success rate per engine
harness engines cooldowns                  # which engines are currently quarantined
```

### 3b. Test one engine in isolation

```bash
PYTHONPATH=src python -c "
import harness
r = harness.dispatch('reply OK', engine='kimi')   # change engine name
print('success:', r.success)
print('error:', r.error_excerpt)
print('engine:', r.engine_used)
"
```

### 3c. Forced fallback

If Kimi is down, `harness review --lens-set default` will still work
because the other 2 engines (DeepSeek + MiMo) are independent.  For
direct dispatches:

```bash
# Use the fallback chain explicitly:
harness dispatch --backend deepseek --packet <(echo "test")
```

### 3d. Quarantine an engine deliberately

```bash
# Not yet wired as a CLI verb; manual via state:
# Edit state/engine_health.json to set quarantined=true on the engine
# (W13-OPERATOR-RUNBOOK note: this should become `harness engines quarantine <name>`)
```

---

## Section 4: Daily operating loop

```bash
# Morning (run during coffee):
bash scripts/v1-rc1-24h-report.sh          # the overnight report
harness today                              # what shipped + L5 events
harness cost-today                         # budget remaining

# Midday (when you've used the harness for an hour):
harness cost-today                         # check spend isn't running away
harness observer flags                     # any pending HIGH/CRITICAL?

# Evening (before walking away):
harness preflight                          # readiness for the overnight
# If anything's red, run `harness preflight --fix --dry-run`
# then drop --dry-run to apply
```

---

## Section 5: When you want to use the harness for actual work

### 5a. Review a document (most common workflow)

```bash
harness review path/to/document.pdf
# Output: coord/reviews/review-<basename>/SYNTHESIS.md

# For source code:
harness review src/foo.py --lens-set code-review

# For documentation:
harness review docs/SOMETHING.md --lens-set doc-review

# Custom output dir:
harness review some.pdf --out-dir /tmp/my-review/

# Tighter token budget (for quick scans):
harness review some.pdf --max-tokens 2000
```

### 5b. Single-shot dispatch

```bash
PYTHONPATH=src python -c "
import harness
r = harness.dispatch('Your prompt here', engine='kimi')
print(r.summary)             # short version, ~300 chars
print(r.full())              # full body if needed (lazy fetch)
"
```

### 5c. Multi-step workflow (planner + workers)

```bash
# Plan a wave from a spec:
harness coord plan --spec spec/your-spec.md --engine mock  # safe test

# Run workers:
harness coord run --spec spec/your-spec.md --run-id <id> --engine swarm/mock

# Integrate (merge worker branches):
harness coord integrate --run-id <id>
```

---

## Section 6: When something looks wrong (debugging)

### 6a. L5 banner appeared

Read the banner: it has a specific `ACTION:` line.  Do that thing.

L5 sources:
- Observer raised a CRITICAL flag → `harness observer flags`
- Observer restart failed 3× consecutively → `harness observer restart`
- Preflight check failed → `harness preflight --fix`
- Cost cap exceeded → check `harness cost-today` + maybe raise `COST_MAX_PER_SESSION`

### 6b. `harness today` shows stale loop

```bash
harness observer watchdog-status           # is watchdog OK or STALE?
# If STALE:
harness observer restart                   # re-arm
# If restart fails 3×, L5 banner fires with manual recovery steps
```

### 6c. `harness preflight` shows FAIL

```bash
harness preflight --fix --dry-run          # preview fixes
harness preflight --fix                    # apply
# Common fails + fixes:
# - pytest_cache: run `pytest` once to populate
# - git_clean: commit or stash your in-progress work
# - dead_engines: check API keys via `harness preflight`
```

### 6d. Dispatch returned success=False unexpectedly

Check `r.error_excerpt` for the cause.  Common ones:
- `adapter_load_failed`: `adapters/<project>/harness-adapter.yaml` missing — SDK auto-bootstrap should handle this; if it doesn't, file an issue
- `engine_pool_exhausted`: all engines in fallback chain failed; check cooldowns + API keys
- `cost_cap_exceeded`: you hit the $5 session cap; raise via `COST_MAX_PER_SESSION` env var

Post-W13-ENGINE-RETRY-RESILIENT (2026-05-25), error strings are now categorized + preserve the actual exception:

- `HTTP <code>`: explicit server response (4xx/5xx) — never retried; check auth + payload
- `remote_protocol_error: <repr>`: server disconnected mid-stream — retried once automatically; if still failing, the server is genuinely down
- `timeout: <Class>: <repr>`: client-side timeout (Read/Connect/Write/Pool) — retried once automatically
- `network: <repr>`: TCP refusal or DNS failure — NOT retried; check network + endpoint
- `unexpected: <ExcType>: <repr>`: bug or unhandled case — preserves the original exception class + repr.  Replaced the old opaque `"internal"` string from the bare-except wrapper.

The harness automatically retries ONCE on `remote_protocol_error` and `timeout` types (transient API noise).  If both attempts fail, the failure surfaces with the LAST attempt's error string preserved.

### 6e. The dashboard at localhost:8765 isn't loading

```bash
# Check if the dashboard process is running:
# (Windows): tasklist | findstr python
# Restart:
PYTHONPATH=src python -m harness dashboard-serve --port 8765 &
```

---

## Section 7: When you want to add a new engine

### 7a. After W15-ENGINE-ABI ships (Wave 15)

Drop a file in `src/harness/engines/<name>.py` implementing the
`EngineABI` protocol.  See `docs/PLUGIN_GUIDE.md`.

### 7b. Today (manual)

1. Edit `src/harness/engines/concrete.py`: add a new class inheriting
   from `Engine`, implementing `dispatch(self, prompt, model, opts)`
2. Add the engine name to `SUPPORTED_BACKENDS` in
   `src/harness/engines/dispatcher.py`
3. Add the engine to the `_subscription_engines` set in `src/harness/_sdk.py`
   IF it's subscription-priced (zero per-call cost)
4. Add a test in `tests/test_engines_<name>.py`
5. Run `pytest tests/test_engines_<name>.py` to verify

This is currently ~1 day of work.  Wave 15 reduces it to ~2 hours.

---

## Section 8: When you want to add a new review lens

Edit `src/harness/review.py`:
1. Add a new `Lens(...)` entry to `DEFAULT_LENSES` (if it should be default)
   OR
2. Add a new entry to `LENS_SETS` with a custom set name

Then test:
```bash
harness review some-doc.md --lens-set <your-new-name>
```

This is currently <30 minutes of work.

---

## Section 9: When a Claude session picks up this project

If you're a Claude (or other agent) reading this and you just got
loaded into a fresh session:

1. Read `CLAUDE.md` first — it has project-level memory + load-bearing rules
2. Read this file (`docs/INTERNAL_OPERATOR_RUNBOOK.md`) — operational knowledge
3. Read `coord/STATUS.csv` — the canonical task tracker, edit on every transition
4. Read `coord/reviews/master-audit-2026-05-25.md` — strategic state
5. Read `coord/reviews/horizon-c-internal-tool-plan.md` — current roadmap
6. Read `docs/AGENT_QUICKSTART.md` — how the SDK works
7. Check `harness today` for current state
8. Check `harness preflight` for readiness
9. If preflight is FAIL, fix that FIRST before any new work

The operator has **full dev authority** on this project (per
`feedback_xaxiu_harness_full_dev_authority` memory): commit/push/dispatch
without per-action confirmation.  Only escalate L5 errors.

The operator is **non-technical** (per `user_non_technical_role` memory):
favor plain-English output, ASCII-safe characters (Windows cp1252),
single-command verbs over multi-step procedures, and operator-readable
error messages over Python tracebacks.

---

## Section 10: Sustainability checklist

The biggest risk for an internal tool with a single operator is
"key-person dependency".  These habits reduce that:

- **Commit every directive**: when the operator says "I prefer X",
  capture it in STATUS.csv notes + a memory entry so future-Claude
  knows the preference without asking.
  Example: commit feeb446 captured "we are comfortable with high max
  token output cap" → next dispatch script used 6000 by default.

- **Document every emergency fix**: when something breaks + you fix
  it, write the runbook entry in the SAME commit.  Don't rely on
  "I'll document it later".

- **Use the harness for the harness**: every time you make a strategic
  decision, dispatch it through `harness review` for cross-engine
  challenge.  This builds the audit trail AND validates the SDK
  against real use.

- **Test the recovery path quarterly**: every 3 months, simulate a
  laptop-dies scenario by cloning the repo to a fresh directory +
  trying to restore from backup.  Find the gaps + fix them.

- **Keep the operator at the loop's center**: the harness's job is to
  protect the operator's time, not to consume it.  If you find yourself
  spending more time maintaining the harness than getting value from it,
  pause and re-evaluate.

---

## Appendix A: Where everything lives

```
xaxiu-harness/
├── src/harness/             # the actual code
│   ├── _sdk.py              # public SDK (dispatch, retrieve, budget_status)
│   ├── review.py            # `harness review <file>` (W12-B)
│   ├── cli.py               # all the CLI verbs
│   ├── engines/             # per-engine adapters (concrete.py + dispatcher.py)
│   ├── observer/            # cycles, watchdog, flags, cron + Task Scheduler
│   └── dashboard/           # FastAPI server + HTML/JS/CSS static assets
│
├── docs/
│   ├── AGENT_QUICKSTART.md       # the 5-min agent onboarding doc
│   ├── INTERNAL_OPERATOR_RUNBOOK.md  # this file
│   └── OPERATOR_RUNBOOK.md       # older operator-facing doc (predates this)
│
├── coord/                  # operator-facing artifacts
│   ├── STATUS.csv          # THE canonical task tracker
│   ├── observer/           # observer state, daily retros, flags
│   ├── reviews/            # audit reports, panel results, syntheses
│   └── coverage/           # E2E proofs (W4-L, W5-E, W11-SDK-E2E)
│
├── spec/                   # wave plans + sample specs
├── tests/                  # 2179+ tests, all green
├── scripts/                # one-off helpers (audit_*, review_*, plan_*)
└── .harness/               # runtime state (gitignored): dispatch cache, config
```

## Appendix B: Memory entries to load at session start

These are operator-level memories (in `~/.claude/projects/...`) that
shape every Claude session on this project:

- `feedback_xaxiu_harness_full_dev_authority`: act as dev manager, commit/push without confirmation, escalate only L5
- `feedback_status_csv_canonical`: STATUS.csv IS the canonical task tracker; edit on every transition
- `user_non_technical_role`: operator is non-technical; plain English, no Python tracebacks unless necessary
- `feedback_kimi_streaming_sse_format`: Kimi requires `stream=true` + handles `data:` and `data: ` SSE prefixes
- `feedback_no_premature_stop`: run `harness session ok-to-stop` before any "session complete" reply
- `feedback_check_memory_first`: grep memory + warehouse before trial-and-error or escalation
- `reference_xaxiu_harness_error_taxonomy`: L1-L5 severity + domain + code scheme

Plus directives captured this session:
- `2026-05-24 max_tokens`: comfortable with high cap; default 6000-8000, opt-down via --quick
- `2026-05-24 reframe`: Horizon C target is INTERNAL TOOL, not commercial product

---

## Appendix C: Common debugging commands

```bash
# What's the observer doing?
PYTHONPATH=src python -c "from harness.observer import state; print(state.read_state().model_dump_json(indent=2))"

# What's in the dispatch cache?
ls -la .harness/dispatched/

# What's the watchdog's verdict?
PYTHONPATH=src python -c "from harness.observer.watchdog import watchdog_status; import json; print(json.dumps(watchdog_status(), indent=2, default=str))"

# Test a single dispatch end-to-end with verbose output:
PYTHONPATH=src python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
import harness
r = harness.dispatch('test', engine='kimi')
print(r)
"

# Inspect a stored dispatch by id:
harness retrieve <dispatch_id> --scope full

# Reset the cost cap for a fresh budget (env var):
export COST_MAX_PER_SESSION=10.00   # raises cap to $10
# or unset to restore default $5:
unset COST_MAX_PER_SESSION
```

---

*End of runbook.  Update this file in the same commit as any
operational change.  Future-you (and future-Claude) will thank you.*
