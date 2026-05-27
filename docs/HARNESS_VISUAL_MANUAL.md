# xaxiu-harness — visual operator manual

A screenshot-driven walkthrough of how to use the harness for cross-engine LLM dispatch.  Intended for both technical and non-technical operators.

> **Just looking for the cheat sheet?** Jump to [§ TL;DR](#tldr).
> **Setting up a fresh machine?** [`docs/OPERATOR_QUICKSTART.md`](OPERATOR_QUICKSTART.md) is the guided install.

---

## TL;DR

xaxiu-harness is a tool for asking 3 different AI models the same question in parallel from your shell, then comparing their answers.  It runs **entirely on your laptop** — nothing is deployed to a server.

For a working install, these are the only four commands you need to know:

```bash
python -m harness setup       # one-time onboarding (or after re-clone)
python -m harness keys serve  # add or rotate API keys via browser
python -m harness doctor      # health check
python -m harness ask "..."   # cross-engine panel — your daily driver
```

Everything else is power-user surface.  Read the rest of this manual for what each one looks like + when to reach for each.

---

## 1.  `harness doctor` — preflight diagnostics

Run this first whenever something feels off, or after any install/clone.

```
harness doctor — preflight diagnostics
==================================================
  [OK] python           Python 3.13 OK
  [OK] git              git installed + identity set
  [OK] claude_binary    claude installed: 2.1.150 (Claude Code)
  [OK] dpapi            DPAPI read works
  [OK] secrets          engine keys available: env=['DEEPSEEK_API_KEY', 'KIMI_API_KEY', 'MIMO_API_KEY']
  [OK] engine_reachability env=MIMO_API_KEY mimo=tokenplan
  [OK] env_var_inventory KIMI_API_KEY:SET, DEEPSEEK_API_KEY:SET, ANTHROPIC_API_KEY:UNSET, ...
  [OK] coord_dir        coord/ is writable
  [OK] task_scheduler   Task Scheduler reachable
==================================================
overall: OK
```

Nine checks.  Each is independent + has an actionable `fix:` hint when red.

### What each severity means

| Glyph | Severity | What it means | What to do |
|---|---|---|---|
| `[OK]` (green) | OK | This check passed | Nothing — move on |
| `[!]` (yellow) | WARN | Works but worth knowing.  Maybe a feature you haven't configured, or a non-Windows platform skipping a Windows-only probe | Read the message; usually safe to ignore unless you want that feature |
| `[X]` (red) | FAIL | Broken — dispatch will likely fail until this is resolved | Read the `fix:` line under the check + run that command |

### Common failures + what to do

| Check failing | What you'll see | Fix |
|---|---|---|
| `python` | `Python 3.10 too old (need ≥3.11)` | Install Python 3.11 or newer from python.org |
| `claude_binary` | `claude CLI not found on PATH` | Install Claude Code from https://docs.claude.com/en/docs/claude-code/setup, restart your shell, re-run doctor |
| `secrets` / `engine_reachability` | `no engine API keys found` | Run `harness keys serve` and paste at least one key, OR set an env var like `KIMI_API_KEY=...` |
| `dpapi` (Windows only) | `DPAPI unreadable` | Run `harness install` to seed the secrets store |
| `coord_dir` | `can't write to coord/` | Check filesystem permissions on the project dir |

Exit code: `0` if all green or warn, `1` if any fail.

---

## 2.  `harness setup` — one-shot guided onboarding

Use this on a brand-new machine, or after re-cloning into a fresh checkout.

```
============================================================
  xaxiu-harness setup wizard
============================================================
  Guided walkthrough from blank machine to first dispatch.
  Press Ctrl+C at any time to abort + return to your shell.

--- Step 1/5: Run preflight diagnostics (harness doctor) ---
  ✓ All 9 checks pass — no setup issues to fix

--- Step 2/5: Claude Code CLI availability check ---

--- Step 3/5: API key configuration ---
  ✓ API keys already configured — skipping keys UI

--- Step 4/5: Wrapper script installation ---
  ✓ All 6 wrapper scripts already installed at C:\Users\xaxiu\.harness\bin

--- Step 5/5: Smoke dispatch ---
  • Firing a 'say OK' dispatch through the first available Pattern B engine...

============================================================
  Setup wizard complete
============================================================
  ✓ Everything is set up.  Try:

    harness ask 'your first question here'
    harness engines list
    harness keys list
```

Five steps, **all consent-gated**.  If you've already done a step, the wizard detects it and skips.  Safe to re-run.

`--non-interactive` accepts defaults at every prompt (skip browser-opens + real dispatch).  Suitable for CI / scripted bootstrap.

---

## ✅ Sanity check — did setup actually work?

After `harness setup` finishes (or anytime you want to confirm the install is healthy), run a single fast smoke test:

```bash
python -m harness ask "Reply with the single word OK." --engines mimo-via-claude --no-save --max-budget-usd 0.05
```

You should see this within ~30s:

```
engine                   OK   elapsed    in     out    cost       alias
---------------------------------------------------------------------------
  mimo-via-claude        OK    8.1s     43     12    $0.0042   k1

  total cost: $0.0042
```

That's success.  You're ready to use `harness ask` for real questions.

**If you get an error instead:**

| Symptom | What it means | Try this |
|---|---|---|
| `FAIL  no API key configured` | Your `.env` or shell env has no key for that engine | `harness keys serve` → paste a key, save, retry |
| `FAIL  subprocess timeout` | The dispatch ran longer than `--max-budget-usd` allowed | Raise the cap: `--max-budget-usd 0.20` |
| `FAIL  claude binary not found` | Claude Code CLI isn't installed | Install from https://docs.claude.com/en/docs/claude-code/setup, then re-run |
| `command not found: harness` | Not in the right Python environment | `pip install -e .` from the repo root, OR always use `python -m harness` instead of `harness` |
| `FAIL  Origin check failed` (Web UI) | You're hitting the keys server from the wrong host | Use the exact URL printed in the terminal (it has the right token) |

Once your sanity smoke returns OK, you can scale up: try the full 3-engine panel (`harness ask "your question"` with no `--engines`) or switch to a different model with `--engines deepseek-via-claude`.

---

## 3.  `harness keys serve` — the multi-key web UI

This is how you paste / rotate / test API keys.  It binds to `127.0.0.1` only (loopback — never reachable from the network) and is gated by a single-session random token.

```
$ python -m harness keys serve
harness keys ui ready at http://127.0.0.1:50373/?token=...
  binds to 127.0.0.1:50373 only
  token-gated; idle timeout 600s
  CTRL+C to exit (or just close the browser).
```

The browser opens to:

![Keys UI showing 7 providers with multi-key slots, dispatch-readiness status, and security note](screenshots/03_keys_ui_full.png)

### What you see in the UI

| Element | What it tells you |
|---|---|
| **Green "Ready"** status pill at the top | Dispatch-readiness: all configured providers have at least one healthy key.  Yellow = degraded but has fallback.  Red = a provider has zero healthy keys. |
| **Path info** "Keys will save to: D:\xaxiu-harness-standalone\.env" | Where the keys land.  Always under the repo root, mode 0600 on POSIX. |
| **Per-provider rows** (Kimi / MiMo / DeepSeek / Qwen / GLM / Anthropic / Gemini) | One card per provider.  "N key configured" badge top-right. |
| **Per-slot rows** within each provider | k1, k2, k3 ... up to 4 slots.  Each row shows: slot number, env var name (e.g. `KIMI_API_KEY_2`), source badge (`legacy` = bare `KIMI_API_KEY`, `shell` = indexed `_n`, `.env` = from .env file, `dpapi` = Windows encrypted, `—` = empty), health badge (green `up` / red category / gray `untested`), password input, Test button, × remove button (on slots 2+) |
| **+ Add another key** button | Click to add a new slot (up to 4 per provider).  No reload needed. |
| **Strategy dropdown** (top-right of providers with ≥2 configured keys) | `rotation` (default), `priority`, or `failover-only`.  Changing it writes to `coord/key_policy.json` and applies to all future dispatches. |
| **Test button per slot** | Live-probes that specific key via the harness's `probe_engine_live`.  Records outcome to the health ledger. |
| **× remove button** | Marks the slot for deletion on Save (sets the env var to empty string + removes from .env). |
| **Save all to .env** (bottom right, green) | Writes any changed slots to the repo's `.env` file with proper quoting + 0600 mode.  Idempotent. |

### Security model (footer is the documentation)

The footer recaps the protection: values single-quoted to neutralize shell expansion on `source .env`, newlines/single-quotes in pasted keys are rejected, server binds 127.0.0.1 only, idle-shuts after 10 min, token-gated.  The full threat model is in [`coord/STATUS.csv`](../coord/STATUS.csv) under `W14-KEYS-UI-SECURITY-PATCH`.

---

## 4.  `harness ask` — your daily-driver cross-engine panel

The single command you'll run most often.

```
$ python -m harness ask "Name three benefits of cross-engine LLM panels in one bullet each."
[ask] firing 3 engines in parallel (budget $0.30 each, timeout 180s)...
      output: D:\xaxiu-harness-standalone\coord\reviews\ask-20260526-220035-name-three-benefits-of-cross-engine-llm-panel

engine                   OK   elapsed    in     out    cost       alias
---------------------------------------------------------------------------
  kimi-via-claude        OK   18.2s    694    287    $0.0091   k1
  mimo-via-claude        OK   81.6s    427    179    $0.0078   k1
  deepseek-via-claude    OK   10.9s   1052    243    $0.0188   k1

  total cost: $0.0357
  saved 3 response files + packet.md + summary.json

  → review at D:\xaxiu-harness-standalone\coord\reviews\ask-20260526-220035-name-three-benefits-of-cross-engine-llm-panels
```

### What `harness ask` does behind the scenes

1. **Fires 3 Pattern B engines in parallel**: `kimi-via-claude`, `mimo-via-claude`, `deepseek-via-claude`.
2. **Each dispatched via `dispatch_with_pool`** — automatic multi-key failover if a key is unhealthy.
3. **Records outcomes** to `coord/key_health.jsonl` so future panel selection consults real data.
4. **Saves under `coord/reviews/ask-<ts>-<slug>/`**:
   - `question.md` — your prompt (for re-runs)
   - `<engine>.md` — full response per engine
   - `packet.md` — concatenated question + 3 responses, **synthesis-ready** (hand to an in-session Claude session for synthesis, or read directly)
   - `summary.json` — programmatic metadata (cost, latency, tokens, winning alias, attempt count)

### Key flags

```bash
harness ask "..."                              # default: 3 engines, full save
harness ask --file question.md                 # read question from a file
harness ask "..." --engines mimo-via-claude    # single engine
harness ask "..." --max-budget-usd 0.50        # raise the per-engine spend cap
harness ask "..." --print-text                 # dump full response to stdout
harness ask "..." --no-save                    # skip saving to disk
harness ask "..." --output /tmp/my-panel       # custom output dir
```

Typical 3-engine audit-class panel costs **$0.20-0.30 total**.  Time: 30s-2min.

### What an output directory looks like

```
coord/reviews/ask-20260526-220035-name-three-benefits-of-cross-engine-llm-panel/
├── question.md                    # what you asked
├── kimi-via-claude.md             # Kimi's response, with timing + cost
├── mimo-via-claude.md             # MiMo's response
├── deepseek-via-claude.md         # DeepSeek's response
├── packet.md                      # all 3 concatenated (synthesis-ready)
└── summary.json                   # machine-readable metadata
```

---

## 5.  `harness engines recommend` — empirical routing

Need to pick an engine for a specific task?  Don't guess — ask the empirical recommender:

```
$ harness engines recommend default
mimo-via-claude
  rationale: MiMo-via-claude scored 100% (31/31 programmatic checks) on a 10-prompt production corpus + is the cheapest of the three.  Latency is 36.8s vs DeepSeek's 10.2s - if you need speed pick the `latency` task class instead (returns DeepSeek-flash).
  alternates: deepseek-via-claude, kimi-via-claude

$ harness engines recommend latency
deepseek-via-claude
  rationale: DeepSeek-flash at 10.2s avg on 10-prompt production corpus (W14-MIMO-PRODUCTION-VALIDATION).  Fastest on every category.
  alternates: mimo-via-claude

$ harness engines recommend cost
mimo-via-claude
  rationale: MiMo-via-claude cheapest on both smoke and production corpora.  Token Plan Pro $50/month buys ~6,200 audit-class dispatches.

$ harness engines recommend audit
deepseek-via-claude
  (model_override: deepseek-v4-pro)
  rationale: Audit step needs a DIFFERENT engine than the producer.  DeepSeek v4-pro is the strongest reasoning model available.
```

| Task class | What it returns | When to use |
|---|---|---|
| `default` | mimo-via-claude | Routine code/reasoning |
| `latency` | deepseek-via-claude | Speed-critical (panels, dashboards) |
| `verbose` | kimi-via-claude | Detailed elaboration / writeups |
| `cost` | mimo-via-claude | High-volume batch dispatch |
| `high-volume` | mimo-via-claude | 100s+ dispatches |
| `multimodal` | mimo-via-claude | Markdown image refs in prompts |
| `audit` | deepseek-via-claude w/ v4-pro override | Ship-critical cross-engine verification |

Engine name goes to **stdout** (pipe-friendly); rationale goes to **stderr** (informational).  So `$(harness engines recommend default)` returns just `mimo-via-claude` for shell scripting.

Full data backing these recommendations: [`spec/engine-routing-empirical.md`](../spec/engine-routing-empirical.md).

---

## 6.  `harness keys list` — per-slot status table

Quick read of every configured key + slot, including health:

```
$ python -m harness keys list

provider               env var                source      key (masked)               health
----------------------------------------------------------------------------------------------------
  Kimi (Moonshot)      KIMI_API_KEY           env-legacy sk-k****************...ApSf  untested
  Kimi (Moonshot)      KIMI_API_KEY_2         missing    (not set)
  MiMo (Xiaomi)        MIMO_API_KEY           env-legacy tp-s******************khm2   up
  MiMo (Xiaomi)        MIMO_API_KEY_2         missing    (not set)
  DeepSeek             DEEPSEEK_API_KEY       env-legacy sk-e******************36ed   untested
  DeepSeek             DEEPSEEK_API_KEY_2     missing    (not set)
  Qwen (Alibaba DashScope) DASHSCOPE_API_KEY  missing    (not set)
  GLM (Zhipu z.ai)     GLM_API_KEY            missing    (not set)
  Anthropic            ANTHROPIC_API_KEY      missing    (not set)
  Google Gemini        GEMINI_API_KEY         missing    (not set)
```

Source column:
- `env` — set in shell env via indexed name (`KIMI_API_KEY_1`)
- `env-legacy` — set in shell env via bare name (`KIMI_API_KEY`)
- `dotenv` — set in repo `.env` file
- `dpapi` — set in Windows DPAPI store (encrypted-at-rest)
- `missing` — not set anywhere

Health column shows the latest probe outcome.  `up` = recent successful probe.  `auth-failed` / `quota-exceeded` / `terminated` = quarantined (next dispatch will skip).  `untested` = no probe yet; click Test in the UI or run `harness keys probe-all`.

`--format json` for programmatic consumption.

---

## 7.  Other useful verbs

```bash
harness engines list                   # show priority/locked/status per engine
harness engines health                 # live-dispatch probe (real call, ~$0.01)
harness engines failures               # last 7d failure summary by category
harness engines install-wrappers       # install claude-mimo / claude-kimi / etc.
harness engines list-wrappers          # show wrapper install + key status

harness keys probe-all                 # live-test every populated slot
harness keys policy get                # show per-provider strategy
harness keys policy set <prefix> <strat>  # change to rotation/priority/failover-only
harness keys forget <prefix> <alias>   # clear health history for a key
harness keys health prune              # compact the JSONL ledger

harness budget show                    # per-engine spend vs caps
harness budget cap set <engine> $X     # set a monthly cap

harness today                          # last 24h activity summary
harness morning-brief                  # daily op brief (issues, commits, engine status)
harness audit show                     # forensic dispatch ledger
```

For the full list: `harness --help`.  Or `harness capabilities` for a programmatic snapshot.

---

## 8.  The optional sibling repo

This repo (`xaxiu-harness`) is the operator CLI + web panel.  A sibling repo (`xaxiu-swarm`) provides agentic multi-file dispatch and is **NOT required for daily use** — `harness ask`, the keys UI, and Pattern B engines all work without it.

If you ever want agentic swarm dispatch (multi-file refactors, multi-turn tool use), clone it separately:

```bash
git clone https://github.com/xaxiuegg/xaxiu-swarm.git
cd xaxiu-swarm && pip install -e .
xaxiu-swarm backends  # verify
```

---

## 9.  Deployment model in one sentence

The harness runs entirely on your laptop.  No server, no container, no cloud — `python -m harness ask "..."` from your local shell makes provider API calls via the local `claude` CLI binary (Pattern B), with your laptop as the sole machine in the loop.

---

## 10.  Cost reference

Production-corpus measured prices (2026-05-26, post MiMo V2.5 price cut):

| Engine | Per audit-class dispatch | Cents per 1k output tokens |
|---|---|---|
| `mimo-via-claude` (TP) | ~$0.008 | ~$0.87 / 1M out |
| `deepseek-via-claude` (flash) | ~$0.015 | ~$0.28 / 1M out |
| `kimi-via-claude` | ~$0.025 | ~$2.30 / 1M out |

A typical 3-engine `harness ask` panel: **$0.20-0.30 total**.  At $50/month MiMo Token Plan Pro, you can run ~6,200 panels.

---

## 11.  Where to look next

| For | Read |
|---|---|
| Fresh-machine install from scratch | [`docs/OPERATOR_QUICKSTART.md`](OPERATOR_QUICKSTART.md) |
| Daily-operations procedures (key rotation, recovery) | [`docs/INTERNAL_OPERATOR_RUNBOOK.md`](INTERNAL_OPERATOR_RUNBOOK.md) |
| Empirical routing data (which engine for what) | [`spec/engine-routing-empirical.md`](../spec/engine-routing-empirical.md) |
| What's shipped / queued / in-flight | [`coord/STATUS.csv`](../coord/STATUS.csv) |
| For AI agents resuming work | [`docs/AGENT_QUICKSTART.md`](AGENT_QUICKSTART.md) |

---

---

## Appendix: how this manual was built

This manual was drafted, then sent through a 3-engine review panel via `harness ask` itself.  The panel ran 2026-05-26 evening; total cost $0.18.

**Convergent feedback (both Kimi + DeepSeek):**
- "What does green/yellow/red mean in `harness doctor`?" — added the severity table to § 1.
- "Need a sanity check after setup" — added the dedicated § Sanity check between setup and keys serve.
- "Two-repo story is over-explained" — trimmed § 8 from a 12-line table + clone block to 4 lines.
- "Cost reference needs a concrete daily-budget example" — kept the prices but added the 6,200-panels-per-$50 anchor in § 10.
- "Deployment model is too architectural for a solo operator" — collapsed to a single sentence in § 9.

**Unique to DeepSeek:** explicit troubleshooting paths for setup failure modes (`NO_KEYS`, `connection refused`, `command not found`) — incorporated into the sanity-check fault table.

**Unique to Kimi:** "first 5 minutes" graceful-degradation pattern (start with one engine, watch failover when keys are missing) — incorporated into the sanity-check flow.

**Honest finding from the panel:** MiMo-via-claude went off-task on this prompt (tried to invoke the Read tool to fetch the manual content I told it to "assume" was attached).  Confirms the known MiMo agent-loop tendency documented in `coord/STATUS.csv` under `W14-MIMO-BLOAT-INVESTIGATION`.  Workaround for similar future prompts: embed the document inline rather than reference it.

Full agent responses: [`coord/reviews/manual-review-2026-05-26/`](../coord/reviews/manual-review-2026-05-26/).
