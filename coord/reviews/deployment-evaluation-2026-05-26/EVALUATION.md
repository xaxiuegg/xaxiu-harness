# Deployment evaluation — 2026-05-26

**Subject**: How well-documented is this repo for deploying onto a new machine?  Does it work for a non-technical operator?  Do we need to clone xaxiu-swarm separately?

**Scope**: Fresh-machine clone-to-first-dispatch path.

## Headline

**Status**: ✅ Deployable end-to-end.  ⚠️ Operator-friendly for **experienced devs** (~5-10 min if all prereqs installed); **moderate friction** for non-technical operators (~25-40 min); **high friction** for users with no prereqs (~60-90 min, dominated by provider account signups + Python/Git install).

**xaxiu-swarm dependency**: Optional but undocumented.  See § "The two-repo story" below.

## Time-to-productive by persona

| Persona | Time | Friction |
|---|---|---|
| Experienced dev, all prereqs + keys ready | **5-10 min** | LOW |
| Non-technical operator, prereqs installed | **25-40 min** | MEDIUM |
| Brand-new operator, blank machine | **60-90 min** | HIGH (dominated by signups + tool installs) |

## What landed today to reduce friction

**Three quick wins** shipped as part of this evaluation:

1. **`.env.example`** at repo root (W14-DEPLOY-QUICKWINS) — single template the operator can `cp .env.example .env` and edit.  Documents all 7 provider env var names + the multi-key pool convention.  Closes the "what env vars do I need?" friction.

2. **`docs/OPERATOR_QUICKSTART.md`** — 250-line non-technical operator guide.  Walks blank-machine → first dispatch in 6 numbered steps including `python -m harness keys serve` for browser-based key entry, `harness doctor` verification, and the optional xaxiu-swarm second-repo story.  Closes the "operator-specific quickstart didn't exist" friction.

3. **README.md quickstart rewritten** — now starts with `python -m harness keys serve` (operator-friendly browser form) before falling back to manual `.env` editing.  Explicitly documents the xaxiu-swarm second-repo dependency as optional + when you'd want it.  Closes the "swarm dependency is invisible" friction.

## The two-repo story

The harness has **two distinct git repos** that work together:

| Repo | Required? | What it does |
|---|---|---|
| **xaxiu-harness** (this repo) | **REQUIRED** | Multi-engine dispatch, panels, Pattern B subprocess engines, keys UI, routing recommender, audit ledger |
| **xaxiu-swarm** (sibling) | **OPTIONAL** | Agentic swarm dispatch (`swarm/kimi`, `swarm/claude-mimo`, etc.) — needed only if you want multi-file refactor / multi-turn agent loop dispatches |

If your workflow is **`harness ask "..."`** or **direct programmatic dispatch via `dispatch_with_pool`** (the new daily-driver patterns), you do NOT need xaxiu-swarm.  You only need it for:
- Agentic in-place file edits via `swarm/kimi` (CLI agent loop)
- Direct REST dispatches via `swarm/deepseek` / `swarm/kimi-api` (when you want raw speed + no Claude Code overhead)
- The new `swarm/claude-*` family (TOS-safe agentic, allowlist-future-proof)

**Verdict**: For the operator's stated primary use case (cross-engine panels), **xaxiu-swarm is OPTIONAL**.  The OPERATOR_QUICKSTART.md mentions it explicitly as a Step 6 (optional).

## Remaining friction (not blocking, but worth queueing)

### High-leverage future improvements

1. **`harness setup` — interactive wizard** (~4-6h)
   Walks operator through env-wizard → harness doctor → keys UI → optional xaxiu-swarm clone → smoke test.  Replaces the current sequence of 3-4 separate commands with one guided flow.  Highest UX gain for non-technical operators.

2. **`--add-to-path` flag for `harness engines install-wrappers`** (~1h)
   Currently `install-wrappers` PRINTS the PATH update command but doesn't execute it; operator has to copy-paste + restart shell.  Consent-gated `--add-to-path` would let the operator opt in to automatic.

3. **`bin/install-harness.sh`** — POSIX sibling to the existing `install-harness.ps1` (~3-4h).
   Linux + macOS parity for the wrapper-install + cron registration story.  Currently Windows-only.

4. **`harness keys set kimi <value>`** — single-command unified config (~2h).
   For operators who don't want the UI or `.env` editing.  Would also enable `harness keys export` / `import` for cross-machine config migration.

### Medium-leverage

5. **Docker image** (~4-6h) — single-image deploy for ephemeral compute (CI runners, cloud sandboxes).  Less relevant for solo operators but useful if work ever moves to shared infrastructure.

6. **First-launch wizard for the keys UI** — instead of showing the form, prompt "you have 0 keys configured; want me to walk you through getting one?" with links to provider signup pages.

## What's documented WELL

- ✅ **`pip install -e .` bootstrapping** — W13-INSTALL-VERIFY CI gate proves this works on fresh venv daily.
- ✅ **`python -m harness` universal form** — W13-PYTHON-M-HARNESS-FORM fixes the Windows+Git Bash PATH gotcha.  CLAUDE.md section 1 leads with this.
- ✅ **`harness keys serve` for browser-based key entry** — operator-friendly, no Python knowledge required.
- ✅ **`harness doctor` for verification** — 6-check traffic-light.  Now discoverable from README.
- ✅ **`harness preflight --fix` for auto-remediation** — handles dirty git, stale pytest cache, dead engines.
- ✅ **Daily runbook** (`docs/INTERNAL_OPERATOR_RUNBOOK.md`) — excellent for maintaining an existing install.

## What's still NOT documented well

- ⚠️ **Claude Code CLI prerequisite** — Pattern B engines need `claude` binary, but the docs assume operator already has it.  OPERATOR_QUICKSTART.md mentions it in the prereqs table but doesn't enforce the check.  (`harness doctor` doesn't check for `claude` either.)
- ⚠️ **POSIX (Linux/macOS) wrapper install** — only Windows installer ships.  Operators on those platforms can't install wrappers via a single command.
- ⚠️ **`harness setup` doesn't exist yet** — operators have to chain `env-wizard` + `doctor` + `keys serve` manually.

## Recommendation

**Today's three quick wins are sufficient to ship.**  The friction points above are improvements, not blockers.

**For the next deployment-focused session**:
1. Ship `harness setup` wizard (4-6h) — biggest single UX improvement
2. Add `claude` binary check to `harness doctor` (~15min) — tiny patch with real value
3. POSIX installer script (3-4h) — unblocks Mac/Linux deploys

These three closes the operator-friendliness gap to ~⭐⭐⭐⭐ (excellent for the project's target user).

## Cost of this evaluation

- 0 dispatches (pure analysis + documentation work)
- ~20 minutes of session time
- 3 new artifacts: `.env.example`, `docs/OPERATOR_QUICKSTART.md`, updated `README.md` quickstart
- 1 evaluation document (this one)
