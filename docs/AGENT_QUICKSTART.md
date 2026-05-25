# Agent Quickstart

**Audience**: an agentic coding agent (Claude, ChatGPT, Cursor, Aider, etc.) cloning the harness repo and wanting to dispatch work to other engines while preserving its own context window.

**Goal**: from `git clone` to a real engine response in under 5 commands.

This guide is validated end-to-end against Kimi, DeepSeek, and MiMo (see `coord/coverage/W11_E2E_SDK_PROOF.md`).

> **Orientation shortcut**: once installed, an agent can self-discover everything below by running two commands — `harness today` (shows shipped today, blockers, **install + capabilities**) and `harness capabilities` (lists SDK functions, CLI verbs, reachable engines, audit ledger path).  These are the live truth; if anything in this doc disagrees, the runtime introspection wins.  See sections 0 and 12.

---

## 0. Orient yourself in 2 commands

After install (section 1), before doing anything else, an agent should run:

```bash
harness today           # shipped in last 24h + blockers + reachable engines + L5 events
harness capabilities    # SDK function list, CLI verb list, engine key presence, audit ledger
```

These are **introspection-only** — no engine dispatch, near-zero cost.  Use them as the source of truth for "what can this binary do right now."  They are protected by a CI gate (`tests/test_docs_no_future_as_present.py`) so they never reference fictional verbs.

The W13-AUDIT-JSONL ledger at `~/.harness/audit.jsonl` records every dispatch with redacted prompt/response excerpts — review it with:

```bash
harness audit show --tail 20         # last 20 dispatch rows (redacted)
harness audit summary --since-hours 24
```

---

## 1. Clone + install

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
pip install -e .       # or `pip install -r requirements.txt`
```

Python 3.13+ recommended (the engine adapters use modern union syntax and `StrEnum`).

## 2. Set engine API keys

The SDK resolves keys in this order: `os.environ` > `.env` file > Windows DPAPI fallback.

For Linux / Mac / WSL, the simplest path is `.env`:

```bash
cat > .env <<'EOF'
KIMI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
MIMO_API_KEY=sk-...
EOF
```

You don't need all three. Kimi is the recommended starter (subscription pricing; zero per-token cost when you have a key).

To verify which keys are loaded without leaking values:

```bash
python -c "from harness.secrets.resolve import source_of; \
[print(f'{k}: {source_of(k)}') for k in ('KIMI_API_KEY','DEEPSEEK_API_KEY','MIMO_API_KEY')]"
```

Output is `env` / `dotenv` / `dpapi` / `missing` — never the key itself.

## 3. (Optional) Initialize a project layout

If you're using the harness inside *your* project (not the harness repo itself), scaffold it:

```bash
harness agent init --target .
# or for a fresh directory:
harness agent init --target ./my-project --project-type python
```

This writes 7 files non-destructively: `.env`, `.gitignore`, `adapter.py`, `CLAUDE.md` (marker-gated append), `.harness/config.json`, `.harness/STATUS.csv`, `.harness/dispatched/.gitkeep`. Re-running is safe — existing files are not overwritten.

Works on Windows / Linux / macOS (Wave 12-A fix to `_bootstrap_utf8_stdout` in `cli.py::main()` reconfigures stdout/stderr to UTF-8 before click writes anything, so the `✓` success-summary glyph and other Unicode in CLI output no longer crash cp1252 consoles).

For the harness repo itself, skip this step.

## 4. Dispatch your first prompt

```python
import harness

result = harness.dispatch("What model are you? Reply in one sentence.", engine="kimi")
print(result.summary)
# 'I am Kimi, a large language model developed by Moonshot AI.'

print(result.success)        # True
print(result.engine_used)    # 'kimi'
print(result.dispatch_id)    # 'cf922c67f58d45819620a566e8d0d10a'
print(result.tokens_in, result.tokens_out)   # 14 110
```

The default mode is **context-frugal**: `result.text` is `None` and only `result.summary` is populated (~300 chars). The full response stays in the dispatch cache for lazy retrieval.

This is the load-bearing design choice — your agent context grows ~36 tokens per dispatch instead of ~1500.

## 5. Lazy-fetch the full text when you actually need it

```python
full_response = result.full()   # round-trips to the cache, populates result.text
print(full_response)
```

Idempotent — second `.full()` is a near-zero local read.

Or retrieve later by id:

```python
body = harness.retrieve(result.dispatch_id, scope="full")
chunks = harness.retrieve(result.dispatch_id, scope="chunks", chunk_size_tokens=500)
```

## 6. Engine fallback chain

Pass a list of engines; the first available one is used:

```python
result = harness.dispatch(
    "complex task",
    engine=["kimi", "deepseek", "mimo"],
)
print(result.engine_used)        # whichever succeeded
print(result.fallback_chain)     # which engines were tried
```

## 7. Monitor your token budget

```python
status = harness.budget_status()
print(status["offload_ratio"])              # 0.36 → 36% of work on subscription engines
print(status["remaining_budget_usd"])       # 4.41 → $4.41 of $5 cap left
print(status["engines_used"])               # {'kimi': 1353, 'deepseek': 2099, ...}
```

Cheap to call (~1KB payload); safe to poll between dispatches without blowing your context.

Operator-readable variant from the CLI:

```bash
harness cost-today
# $0.2595 spent / $5.00 budget (today) - 2387 sub, 1693 paid (16% offload)  [ok]
```

## 8. When something escalates

The harness uses a 5-level severity scheme (L1 INFO → L5 FATAL). Only L5 demands operator action. When an L5 fires, you (or your operator) will see this banner:

```
============================================================
L5 ESCALATION — L5.observer.OBSERVER_RESTART_LOOP
============================================================
observer scheduler restart failed 3 consecutive times — the watchdog
cannot self-recover

ACTION: Inspect scheduler manually: on Windows run
`Get-ScheduledTask -TaskName XaxiuHarnessObserver*`; on Linux/Mac
run `crontab -l | grep HARNESS_OBSERVER`. Then run
`harness observer install-scheduler` with elevated privileges if needed.

Evidence:
  - latest register message: PowerShell exit code 1
  - cadence: every 60 min
  - daily retro at: 23:00
============================================================
```

Banner is visually distinct: 60-char border + `L5 ESCALATION` header + `ACTION:` callout + optional evidence block. Don't suppress these.

`harness today` always surfaces the last 24h of L5 events:

```bash
harness today --since-hours 24
```

## 9. Anti-patterns

- **DO NOT** call `harness.dispatch(prompt, return_mode="full")` as your default — that's the legacy behavior; you'll burn ~750KB context across 30 dispatches.
- **DO NOT** save `result.text` to long-term memory if your `result.text` is `None` — call `.full()` first.
- **DO NOT** dispatch to `--backend claude` (no cross-engine value + ANTHROPIC_API_KEY pollution; use Claude in-session instead).
- **DO NOT** bypass the budget cap (`COST_MAX_PER_SESSION` env override exists but escalates to L5 when exceeded).

## 10. The API surface, briefly

```python
# harness/__init__.py re-exports (validated by tests/test_docs_mention_all_sdk_fns.py):
dispatch(prompt, engine=None, *, return_mode='summary', timeout_sec=420.0,
         with_full_text=False, no_cache=False) -> DispatchResult

retrieve(dispatch_id, scope='summary'|'full'|'chunks', *,
         chunk_size_tokens=2000, project_root=None) -> str | list[str]

budget_status(*, since_hours=None, ledger_path=None) -> dict

review(document_path, *, lens_set=None, max_tokens=None, quick=False,
       out_dir=None, max_concurrent=3, progress_cb=None) -> ReviewResult
    # W13 Wed-Thu bundle: multi-engine document review.  lens_set=None
    # auto-picks from file extension (.py->code-review, .md/.pdf->doc-
    # review, else 'default').  max_tokens=None resolves via safe-floor
    # (4000 default; quick=True drops to 1000; explicit int wins).

capabilities() -> dict
    # Cheap introspection.  Returns {version, python_version, platform,
    # sdk_functions, cli_verbs, review (lens_sets+supported_extensions+
    # default_max_tokens+quick_max_tokens), engines (configured+
    # keys_present), audit (ledger_path+max_age_days)}.

# DispatchResult attributes (context-frugal defaults):
.success      bool
.engine_used  str
.dispatch_id  str
.summary      str        # ~300 chars; always populated
.truncated    bool       # True when full text is in cache, not in .text
.text         str | None # None by default; .full() populates
.error_excerpt str | None
.content_ref  str | None
.tokens_in, .tokens_out, .cost_usd
.fallback_chain  list[str]

.full() -> str           # lazy round-trip to cache + retrieve()

# ReviewResult attributes:
.synthesis_path   str    # path to SYNTHESIS.md (most agents only need this)
.out_dir          str
.document_text_length  int
.elapsed_s        float
.total_cost_usd   float
.successful_lenses, .failed_lenses  int
.lens_set_used    str
.max_tokens_used  int
.lens_results     list[dict]  # per-lens engine + ok + tokens + cost

# Exceptions:
HarnessSDKError              # base
ResultNotFoundError          # dispatch_id has no cached body
ResultCorruptedError         # cached payload malformed
```

Type stubs live in `src/harness/__init__.pyi` for IDE autocomplete.  A CI gate
(`tests/test_docs_mention_all_sdk_fns.py`) fails the build if anything in
`harness.__all__` is missing from this section.

## 11. Where to look next

- `CLAUDE.md` — project memory + operator directives
- `coord/STATUS.csv` — canonical task tracker (this is THE source of truth)
- `coord/CURRENT_PLAN.md` — active strategic plan (also surfaced via `harness plan show`)
- `spec/` — wave plans + acceptance criteria
- `coord/coverage/W11_E2E_SDK_PROOF.md` — the live-engine E2E proof this quickstart is validated against
- `docs/INTERNAL_OPERATOR_RUNBOOK.md` — laptop-dies / key-rotation / engine-down / daily-loop / debugging procedures
- `harness --help` — full CLI surface (`harness advanced list` shows the hidden engineering verbs)

If `harness.dispatch()` returns `success=False` with a message you don't understand, run `harness preflight` and look for the `L5 ESCALATION` banner — it will name the exact next action.

## 12. Hallucination-resistance checklist

Before claiming a verb / SDK function / behavior exists, an agent should:

1. **Trust the binary, not the doc.**  Run `harness capabilities` for the live SDK + CLI surface, or `harness <verb> --help` for verb-level signatures.
2. **Check STATUS.csv for shipped status.**  Rows tagged `shipped` are done; `todo` / `in_progress` are not.  Don't claim a `todo` row is shipped.
3. **Use `harness audit show` to verify dispatch history**, not memory of what you "think happened" earlier in the session.
4. **CI gates that already protect you**:
   - `tests/test_docs_no_future_as_present.py` — fails if a doc references a non-registered CLI verb
   - `tests/test_docs_mention_all_sdk_fns.py` — fails if `harness.__all__` adds a public name this doc doesn't mention
   - `tests/test_install_verify.py` (W13) — fails if `pip install -e .` doesn't produce a working `harness` console script with the public SDK importable

If you propose a behavior and a CI gate isn't covering it, that's a row worth filing.
