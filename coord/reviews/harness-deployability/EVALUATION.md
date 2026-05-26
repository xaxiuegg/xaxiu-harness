# Harness deployability evaluation

**Date**: 2026-05-26
**Question**: *how deployable-friendly is the harness when git-cloned? how fast can it be deployed to a new computer?*
**Method**: walk the actual recipe end-to-end, time each step, identify friction points, propose specific improvements.

## Headline

**Time to first successful dispatch on a fresh machine: ~25-40 minutes for an experienced developer; ~60-90 minutes for someone unfamiliar with the prerequisites.**

The harness has good `pip install` ergonomics (W13-INSTALL-VERIFY gates this on every PR) but several deploy-time friction points remain:

1. Three external prerequisites the harness can't install itself: Python 3.13+, Node.js 18+, and the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
2. API keys are 3-5 separate env-var sets (no single config or wizard)
3. The `~/.harness/bin` wrapper directory needs manual PATH-add
4. No `harness doctor` / `harness setup` to summarize all of this in one command

None of these are blockers. The harness DOES install and run today. But "10 minute deployment to a new machine" requires `harness doctor` + `harness setup` (proposed at the bottom).

## The actual recipe (fresh machine, walked end-to-end)

### Step 0 — Prerequisites (manual)

| Component | Why | Install time |
|---|---|---|
| Python 3.13+ | The harness lib + tests | 2-5 min (already-installed: 0) |
| Node.js 18+ | Required by `claude` CLI | 3-5 min (already-installed: 0) |
| Git | Cloning the repo | 2 min (already-installed: 0) |
| `claude` CLI (Anthropic Claude Code) | Required for Pattern B (kimi-via-claude / mimo-via-claude / deepseek-via-claude) | `npm install -g @anthropic-ai/claude-code` — 1-2 min |
| Anthropic API key OR Claude Code subscription | First-launch onboarding bypass for the `claude` binary | 5 min (account creation) |

**Subtotal**: 10-20 min on a truly fresh machine; 0-2 min if the dev box already has Python/Node/Git.

### Step 1 — Clone + pip install

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness-standalone
pip install -e . --quiet
```

**Time**: ~30s. Validated by W13-INSTALL-VERIFY (`test_install_verify.py`) on every PR.

### Step 2 — Set engine keys

```bash
# Edit ~/.bashrc or ~/.zshrc or Windows env panel
export KIMI_API_KEY=sk-...
export MIMO_API_KEY=tp-...
export DEEPSEEK_API_KEY=sk-...
# Optional providers (when subscribed):
export GLM_API_KEY=sk-...
export DASHSCOPE_API_KEY=sk-...
```

**Time**: 2-5 min if keys are already provisioned, longer if signing up for each provider.

The operator's `.env` file fallback (`harness.secrets.resolve.resolve_key`) works as an alternative — drop a `.env` in the repo root. But on Windows, env vars in the shell are usually the path of least resistance.

### Step 3 — Orient + verify

```bash
python -m harness today          # last 24h ship list + L5 events + capabilities
python -m harness plan show      # current strategic plan
python -m harness engines --health     # live probe of each engine
python -m harness engines --list       # priority + status table
python -m harness budget caps          # per-engine spend vs cap
```

**Time**: ~30s end-to-end. Each verb is fast; `engines --health` does a real 5-token probe per engine so it's the slowest at ~10-15s.

**Friction surfaced today**: `engines --health` shows `kimi: terminated` (TOS-gate for truthful UA), correctly per W14-MIMO-TOS-COMPLIANCE. New operator may not understand why; needs better docs at this junction.

### Step 4 — Install Pattern B wrappers + PATH

```bash
python -m harness engines install-wrappers
```

This writes `claude-mimo`, `claude-kimi`, `claude-deepseek`, etc. to `~/.harness/bin/`.

The CLI prints the PATH hint:

```
NOTE: wrapper dir is not on your PATH.
Add the wrapper dir to PATH:
  PowerShell:  [Environment]::SetEnvironmentVariable("PATH", "$env:PATH;C:\Users\xaxiu\.harness\bin", [EnvironmentVariableTarget]::User)
  cmd:         setx PATH "%PATH%;C:\Users\xaxiu\.harness\bin"
```

**Time**: 30s for the wrapper install; **5-10 min for the PATH change to propagate** (Windows requires shell restart; Unix needs `.bashrc` reload).

### Step 5 — First real dispatch

```bash
# Via wrapper (after PATH is updated)
claude-kimi "Hello, who are you?"

# OR via the harness SDK without PATH change
python -c "
from harness.engines.concrete import get_engine
e = get_engine('kimi-via-claude')
r = e.dispatch('Hello', '', {'max_budget_usd': 0.10})
print(r.text)
"
```

**Time**: 5-30s per dispatch. First dispatch is slowest (subprocess spawn + Claude Code init + provider HTTP).

### Step 6 — First-launch onboarding (one-time, hidden)

The first time `claude` is invoked on the machine, it may prompt for Anthropic login. We handle this via `_ensure_onboarding_bypass` (W14-PATTERN-B-SECONDARY) which writes `hasCompletedOnboarding: true` to `~/.claude.json`. The operator may still need to log in via `claude /login` separately for some workflows.

**Time**: 0s if already done; up to 5 min for a fresh login if needed.

## End-to-end time-to-productive

| Scenario | Estimated time |
|---|---|
| Experienced dev, all prerequisites already installed, keys provisioned | **5-10 min** |
| Experienced dev, fresh box, has provider accounts | **25-35 min** |
| New operator, fresh box, no accounts yet | **60-90 min** (dominated by provider signups) |

## Friction points (ranked)

### 1. No unified prerequisite check

There's no `harness doctor` that tells you: "Python OK, Node MISSING (install via …), Git OK, claude CLI MISSING (install via npm install -g @anthropic-ai/claude-code), keys: KIMI_API_KEY OK / DEEPSEEK_API_KEY MISSING / MIMO_API_KEY OK / GLM_API_KEY MISSING / DASHSCOPE_API_KEY MISSING". The operator has to discover missing pieces ad-hoc.

**Highest-leverage fix**: ship `harness doctor`.

### 2. PATH update is manual + requires shell restart

The `install-wrappers` prints the right command but doesn't run it (correctly — modifying the operator's shell env without permission is hostile). However, the operator has to (a) read the hint, (b) run the PowerShell or shell command, (c) restart their shell. A `--add-to-path` flag with explicit consent would shave 5 minutes off.

### 3. Three OS-specific prerequisite paths

- Linux/Mac: `apt install python3.13 nodejs && curl ...`
- Windows: install Python + Node from .exe; install via PowerShell
- WSL: hybrid

We have an `install-harness.ps1` but it's Windows-only. No equivalent for Linux/Mac.

### 4. First-launch Claude Code onboarding can stall the first subprocess

W14-PATTERN-B-SECONDARY's `_ensure_onboarding_bypass` handles this for Pattern B dispatches. But if the operator calls `claude` directly first, they get the interactive prompt. The wrapper scripts could pre-run the bypass once.

### 5. Multiple API key env vars

Each provider has its own env var (KIMI_API_KEY, MIMO_API_KEY, DEEPSEEK_API_KEY, GLM_API_KEY, DASHSCOPE_API_KEY). No unified config like `~/.harness/keys.json` or a `harness keys set` command. For a solo operator with 5+ providers, this is real friction.

## What's already good

- **`pip install -e .` is fast and idempotent** (~30s, gated by W13-INSTALL-VERIFY)
- **`harness today` + `harness plan show` give immediate orientation** to a fresh agent (W13-DOC-SDK-COVERAGE + W13-HARNESS-PLAN-VERB)
- **The `.env` file fallback** lets operators avoid shell config files
- **Live engine-health probes** (W13-ENGINE-FAILURE-VISIBILITY) catch dead providers immediately
- **`harness engines install-wrappers`** ships Pattern B in one command (no manual script editing)
- **Tests cover the install path** (`test_install_verify.py` runs `pip install -e .` on a fresh venv every CI run)

## Proposed: `harness doctor` (highest-leverage improvement)

One CLI verb that summarizes the entire deployment state:

```
$ harness doctor

System prerequisites:
  ✓ Python 3.13.13         (>=3.13 OK)
  ✓ Node.js 18.16.1        (>=18 OK)
  ✓ Git 2.45.1
  ✓ claude CLI 2.1.150     (~/.local/bin/claude)
  ✓ harness 0.1.0          (installed in editable mode)

API keys (env or .env):
  ✓ KIMI_API_KEY           sk-...pSf       (Kimi Code subscription)
  ✓ MIMO_API_KEY           tp-...          (MiMo Token Plan SGP)
  ✓ DEEPSEEK_API_KEY       sk-...          (DeepSeek PAYG)
  ✗ GLM_API_KEY            missing         (set if subscribing to z.ai)
  ✗ DASHSCOPE_API_KEY      missing         (set for Qwen)
  ✗ ANTHROPIC_API_KEY      missing         (optional; for direct httpx)

Pattern B wrappers (~/.harness/bin):
  ✓ claude-mimo            installed
  ✓ claude-mimo-payg       installed
  ✓ claude-kimi            installed
  ✓ claude-deepseek        installed
  ✓ claude-glm             installed       (will fail at runtime; GLM_API_KEY missing)
  ✓ claude-qwen            installed       (will fail at runtime; DASHSCOPE_API_KEY missing)

  ⚠ ~/.harness/bin is NOT on PATH.  Wrappers are usable only via full path.
    Fix: setx PATH "%PATH%;C:\Users\xaxiu\.harness\bin"   (Windows)
    Fix: echo 'export PATH="$PATH:$HOME/.harness/bin"' >> ~/.bashrc   (POSIX)

Engine health (live probes):
  ✓ deepseek (direct httpx)        up
  ✗ kimi     (direct httpx)        terminated (UA-gate; use kimi-via-claude)
  ✗ anthropic (direct httpx)       no-key (optional)
  ✗ gemini   (direct httpx)        no-key (optional)
  ✓ mimo     (direct httpx)        up

Audit ledger:
  ✓ ~/.harness/audit.jsonl         309 events in last 30d ($0.18 spent)
  ✓ state/engine_performance_log.jsonl  2745 events in last 30d

Budget caps:
  Global cap:  $0.6571 / $95.00 (0.7%)  OK
  deepseek     $0.66 / $30.00 (2.2%)    OK
  mimo         $0.00 / $15.00 (0.0%)    OK
  qwen         $0.00 / $50.00 (0.0%)    OK

Exit code: 0 (deployment ready) -- 2 missing optional keys + 1 PATH warning.
```

This single command surfaces everything a new operator needs to fix. Effort: ~3-4h to implement (composes existing introspection — `capabilities`, `engines --health`, `engines list-wrappers`, `budget caps`, plus prereq checks).

## Proposed: `harness setup` (interactive guided setup)

A wizard that walks through prereq install + key entry + wrapper install + PATH add, with operator consent at each step:

```
$ harness setup

Welcome to xaxiu-harness setup.

Checking prerequisites...
  ✗ claude CLI not found.  Install via:
    npm install -g @anthropic-ai/claude-code
  Run this for you? [y/N]: y
  (running...)
  ✓ Installed claude 2.1.150

Checking API keys...
  ✗ KIMI_API_KEY not set.
  Paste it now (or press Enter to skip): sk-...pSf
  ✓ Stored in ~/.env (mode 600)

  (... similar prompts for other keys ...)

Installing Pattern B wrappers...
  ✓ ~/.harness/bin/claude-mimo
  ✓ ~/.harness/bin/claude-kimi
  ...

Add ~/.harness/bin to PATH? [y/N]: y
  ✓ Appended to ~/.bashrc

Running first-dispatch smoke test...
  ✓ kimi-via-claude:    "OK" ($0.0068, 6.2s)
  ✓ mimo-via-claude:    "OK" ($0.0098, 8.1s)
  ✓ deepseek-via-claude: skipped (would cost ~$0.02 -- run with --full for full smoke)

Deployment complete in 4m 12s.  Total cost: $0.0166.
Open a new terminal to pick up the PATH change.
```

Effort: ~6-8h (it's a guided harness over `doctor` + interactive prompts + opt-in PATH edits + secret-file writes).

## Specific deployability improvements (ranked by leverage/effort ratio)

| Row | Effort | Why |
|---|---|---|
| **W14-HARNESS-DOCTOR** | ~3-4h | Single command surfaces all friction points; eliminates "what's missing?" guesswork |
| **W14-WRAPPER-AUTO-PATH** | ~1-2h | Add `--add-to-path` flag to `install-wrappers` (consent-gated); shaves 5-10 min off deployment |
| **W14-LINUX-MAC-INSTALLER** | ~3-4h | Sibling to the existing `install-harness.ps1` for POSIX shells |
| **W14-HARNESS-SETUP-WIZARD** | ~6-8h | Interactive guided setup; ideal for new-machine deployment |
| **W14-UNIFIED-KEY-CONFIG** | ~2h | `harness keys set kimi <value>` + `~/.harness/keys.json` storage with file-mode 600 |
| **W14-DEPLOY-DOCKER-IMAGE** | ~4-6h | Self-contained image with Python + Node + claude + harness preinstalled; for ephemeral compute scenarios |

## Verdict

**The harness is deployable but not deploy-friendly.** A new computer can be productive in ~25-40 min today; with `harness doctor` and `harness setup`, that drops to ~10-15 min for an experienced operator (mostly dominated by external prerequisite installation).

If the operator wants to seriously prioritize multi-machine deployment, the right next step is **W14-HARNESS-DOCTOR** (3-4h) — it pays for itself the second machine onwards, and the diagnostic output is also useful for debugging existing installs.

The harness has been built for "one operator, one workstation, set up once." For "multiple machines, deployed on demand," the existing infrastructure is roughly 60% complete; the remaining 40% is in `doctor` + `setup` + Linux/Mac installer parity.
