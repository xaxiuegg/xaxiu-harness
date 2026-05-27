# Operator quickstart — fresh-machine setup in ~30 minutes

This is the **non-technical operator** guide: how to get xaxiu-harness running on a brand-new computer.  No prior knowledge of Python or git required, but you'll need to be comfortable running shell commands.

If you've done this before and just need the cheat sheet → see [README.md § Quick start](../README.md#quick-start-fresh-machine).

---

## Prerequisites you need installed first

Skip these if you already have them.  Total install time if you don't: ~10-15 min.

| Tool | Why | Get it from |
|---|---|---|
| **Python 3.13** (or 3.11+) | Runs the harness. | https://www.python.org/downloads/ |
| **Git** | Clones the repo. | https://git-scm.com/downloads |
| **Claude Code CLI** | Pattern B engines route through Claude Code's subscription. | https://docs.claude.com/en/docs/claude-code/setup |

**Optional but recommended**:
- A code editor (VS Code is free + popular)
- Windows: Git Bash or PowerShell (both work)

---

## Step 1 — Clone and install the repo

Open a terminal (PowerShell on Windows, Terminal on Mac/Linux) and run:

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
python -m venv .venv
```

Activate the venv:
- **Windows PowerShell**: `.venv\Scripts\Activate.ps1`
- **Windows Git Bash**: `source .venv/Scripts/activate`
- **Mac/Linux**: `source .venv/bin/activate`

Then install:

```bash
pip install -e .
```

Takes ~30 seconds.  Should print "Successfully installed xaxiu-harness".

**Verify the install works**:

```bash
python -m harness --help
```

If you see a list of commands, you're good.

> **Why `python -m harness` and not just `harness`?** On Windows + Git Bash, `harness` (the .exe shortcut pip created) often isn't on your PATH.  `python -m harness` always works.  Once you've confirmed it works either way, you can use whichever you prefer.

---

## Step 2 — Configure your API keys

You need API keys for the AI providers you want to dispatch to.  **You don't need all of them.**  At minimum you need ONE working key (the harness will tell you if everything is missing).

**Easiest path: the keys UI.**  Run:

```bash
python -m harness keys serve
```

This opens a browser form at `http://127.0.0.1:<random-port>` where you can:
- Paste each provider's API key
- Click **Test** to verify the key works (live probe to the provider)
- Click **Save all to .env** to save them to your repo's `.env` file (with 0600 file mode on Mac/Linux — operator-only readable)

| Provider | Get a key at | Required? |
|---|---|---|
| Kimi (Moonshot) | https://platform.moonshot.cn/ | Recommended |
| MiMo (Xiaomi) | https://mimo.xiaomi.com/ | Recommended (cheapest!) |
| DeepSeek | https://platform.deepseek.com/ | Recommended (fastest) |
| Anthropic | https://console.anthropic.com/ | Optional |
| Gemini (Google) | https://aistudio.google.com/ | Optional |
| Qwen (Alibaba) | https://dashscope.console.aliyun.com/ | Optional |
| GLM (Zhipu z.ai) | https://www.bigmodel.cn/ | Optional |

**Alternative: edit `.env` by hand.**  Copy the template and fill it in:

```bash
cp .env.example .env
# Then edit .env in your text editor
```

The template has comments explaining each field.

---

## Step 3 — Verify everything's wired up

```bash
python -m harness doctor
```

Six-check traffic light:

- ✅ Python + git installed
- ✅ Repo is in a clean git state
- ✅ DPAPI is reachable (Windows) / secrets resolver works (Mac/Linux)
- ✅ At least one API key is set
- ✅ `coord/` directory is writable
- ✅ Task Scheduler (Windows) / cron (POSIX) state — only relevant if you want autonomous mode

Anything red has an explicit "Run to fix" hint.

If `harness doctor` is all green, you're ready to dispatch.

---

## Step 4 — Run your first cross-engine panel

The headline use case: ask one question, get 3 independent engine perspectives.

```bash
python -m harness ask "what's a good first project for learning Python?"
```

This dispatches to Kimi + MiMo + DeepSeek in parallel.  Takes 30s-2min depending on which engines respond fastest.  Writes everything to `coord/reviews/ask-<timestamp>-<slug>/`:

- `question.md` — your question (for re-runs)
- `kimi-via-claude.md` — Kimi's response
- `mimo-via-claude.md` — MiMo's response
- `deepseek-via-claude.md` — DeepSeek's response
- `packet.md` — all three concatenated (synthesis-ready)
- `summary.json` — programmatic re-use

Typical cost: $0.20-0.30 total.  See `harness ask --help` for options.

---

## Step 5 — Optional: install the wrapper scripts

For interactive use (you typing commands directly to an engine), install per-provider wrappers:

```bash
python -m harness engines install-wrappers
```

This creates shortcuts under `~/.harness/bin/`:
- `claude-kimi "your prompt"` — interactive Claude Code session routed to Kimi
- `claude-mimo "..."` — same for MiMo
- `claude-deepseek "..."` — same for DeepSeek

Add `~/.harness/bin` to your PATH (the command will tell you how).

These wrappers give you the full Claude Code experience (tools, multi-turn, in-place edits) routed to whichever provider you pick.  Use them when you want to chat interactively rather than dispatch programmatically.

---

## Step 6 — Optional: clone xaxiu-swarm for agentic dispatch

If you want **swarm-style agentic dispatch** (multi-file refactors, batch parallel work), also clone the sibling repo:

```bash
cd ..  # back out of xaxiu-harness
git clone https://github.com/xaxiuegg/xaxiu-swarm.git
cd xaxiu-swarm
pip install -e .
```

Or via uv:

```bash
uv tool install --from D:/Projects/xaxiu-swarm xaxiu-swarm
```

(Replace the path with wherever you cloned it.)

Then verify:

```bash
xaxiu-swarm backends
```

You should see a list including `claude-mimo`, `claude-kimi`, `claude-deepseek` (the TOS-safe agentic family) plus `deepseek`, `kimi`, `kimi-api` (legacy direct paths).

**You only need this second repo if you want the swarm path.**  Everything in step 4 (the `harness ask` panel + `harness dispatch` direct engine calls) works without xaxiu-swarm.

---

## Daily use

Once setup is done, your daily-driver commands are:

```bash
# Ask a cross-engine panel (the most common use case)
harness ask "your question here"

# Check engine health
harness engines list
harness engines health

# Check your spending
harness budget show

# Generate a morning brief (open issues, recent commits, engine status)
harness morning-brief
```

For maintenance procedures (rotating keys, debugging engine failures, recovering from a laptop crash), see [`INTERNAL_OPERATOR_RUNBOOK.md`](INTERNAL_OPERATOR_RUNBOOK.md).

---

## Common issues + fixes

### `harness: command not found` after `pip install -e .`

This means pip's Scripts directory isn't on your PATH.  Two fixes:

- **Always use `python -m harness`** — works regardless of PATH
- **Add the Scripts dir to PATH** — pip's install message tells you the exact path

### `harness doctor` shows "no API key set"

Run `python -m harness keys serve` and paste keys.  Or copy `.env.example` to `.env` and fill in.

### A specific engine keeps failing

```bash
harness engines health      # see which one is red
harness engines failures    # last-7-days failure summary
harness keys probe-all      # live-test every configured key
```

Per-key health is tracked in `coord/key_health.jsonl`.  If a key has been quarantined and you've fixed the underlying issue (re-enabled the account, etc.):

```bash
harness keys forget KIMI_API_KEY k2   # clears health history for that key
```

### Pattern B engines (`*-via-claude`) fail with "claude binary not found"

You need Claude Code CLI installed.  Get it from https://docs.claude.com/en/docs/claude-code/setup — the harness's Pattern B path runs `claude` as a subprocess.

### I want to test the keys UI but my browser doesn't open

```bash
python -m harness keys serve --no-open
```

Prints the URL.  Copy + paste it into your browser manually.  The URL includes a token that's required for access (so it's safe to share for IT support but rotates every session).

---

## Where things live (filesystem map)

```
xaxiu-harness/
├── .env                  ← your keys (gitignored, you fill in)
├── .env.example          ← template to copy from
├── src/harness/          ← Python source
├── tests/                ← test suite (run with `pytest`)
├── coord/                ← shared state + reviews + STATUS.csv
│   ├── STATUS.csv        ← canonical task tracker
│   ├── key_health.jsonl  ← per-key dispatch outcomes
│   ├── key_policy.json   ← per-provider failover strategy
│   └── reviews/          ← every `harness ask` output lives here
├── docs/                 ← guides + runbooks
└── spec/                 ← architectural specs

~/.harness/               ← per-machine state (created on first use)
├── audit.jsonl           ← W13-AUDIT-JSONL forensic ledger
├── bin/                  ← claude-mimo, claude-kimi, etc. wrappers
└── ...
```

---

## Where to read next

- [`README.md`](../README.md) — feature highlights + CLI verb table
- [`docs/INTERNAL_OPERATOR_RUNBOOK.md`](INTERNAL_OPERATOR_RUNBOOK.md) — daily operational procedures
- [`docs/AGENT_QUICKSTART.md`](AGENT_QUICKSTART.md) — for AI agents resuming work on this codebase
- [`spec/engine-routing-empirical.md`](../spec/engine-routing-empirical.md) — when to use which engine, with hard data
- [`coord/STATUS.csv`](../coord/STATUS.csv) — what's been shipped, queued, in-flight
