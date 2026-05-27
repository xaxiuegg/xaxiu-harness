# Using the harness from other projects

Once xaxiu-harness is installed on your machine, you can use it from any directory.  This doc explains where the harness lives, how it stays available across projects, and how to teach a new Claude Code session that it exists.

## Where everything is

After running `pip install -e .` once in the harness repo:

| What | Where | Purpose |
|---|---|---|
| Python source | `<repo>/src/harness/` | The package code, edited in place |
| Editable install link | `<python-site-packages>/xaxiu-harness.egg-link` | Points back at the repo so changes apply immediately |
| `harness` CLI binary | `<python-scripts>/harness.exe` (Windows) or `<python-bin>/harness` (POSIX) | Sometimes not on PATH; `python -m harness` always works |
| `.env` (keys) | `<repo>/.env` | Read regardless of cwd — `_resolve_env_path()` walks up from the package |
| `coord/` (state + reviews) | `<repo>/coord/` | All `harness ask` outputs land here, NOT in the project you ran from |
| `~/.harness/` | `C:\Users\<you>\.harness\` (Windows) or `~/.harness/` (POSIX) | Per-machine: forensic audit ledger, wrapper scripts |

**You can find your install path anytime**:

```bash
python -c "import harness; from pathlib import Path; print(Path(harness.__file__).resolve().parents[1])"
```

Or print the operator-friendly snippet with the path baked in:

```bash
python -m harness agent-instructions --format short
```

## The "harness follows you" model

You DON'T have to be in the harness repo to use it.  Once installed:

```bash
# In any project directory:
cd ~/Projects/my-new-thing
python -m harness ask "should I use sqlite or postgres for this?"
# → fires the panel, saves to <harness-repo>/coord/reviews/ask-<ts>-<slug>/
```

Outputs land in the **harness repo's** coord/reviews/, not your new project's directory.  That's intentional — your project dirs stay clean, and all your panel history accumulates in one place.

## Teaching a new agent session that the harness exists

By default, an agent (Claude Code, Cursor, etc.) opened in `~/Projects/my-new-thing/` has no idea xaxiu-harness is installed.  You have three options:

### Option 1: User-level Claude Code memory (recommended, set once)

Add a section to your user-level CLAUDE.md (the one Claude Code reads on every session):

```bash
python -m harness agent-instructions --format claude-md >> ~/.claude/CLAUDE.md
```

Now every Claude Code session you start, in any directory on this machine, has the harness in its context.  No per-session paste required.

### Option 2: Per-project CLAUDE.md

If a specific project should know about the harness but you don't want it global, drop the snippet into that project's `CLAUDE.md`:

```bash
cd ~/Projects/my-new-thing
python -m harness agent-instructions --format claude-md >> CLAUDE.md
```

### Option 3: One-shot paste

If you don't want any persistent config, just paste this into a new agent session when you want to use the harness:

```bash
python -m harness agent-instructions --format prompt
```

Pipe it to your clipboard:

```bash
python -m harness agent-instructions --format prompt | clip       # Windows
python -m harness agent-instructions --format prompt | pbcopy     # macOS
python -m harness agent-instructions --format prompt | xclip      # Linux
```

Then paste into the agent and it'll know what to do.

## What the agent will be told

The `claude-md` format produces a full section explaining:

- Where the harness is installed (absolute path baked in)
- The four key verbs: `harness ask`, `harness doctor`, `harness engines recommend`, `harness keys serve`
- When to reach for `harness ask` ("second opinion", "cross-engine review", high-stakes decisions) — and when NOT to (every prompt; costs $0.20-0.30)
- The output directory convention (timestamped + slugified under `coord/reviews/`)
- Wrapper scripts in `~/.harness/bin/`
- Pointer to `docs/HARNESS_VISUAL_MANUAL.md` for the full reference

You can preview what the agent will see:

```bash
python -m harness agent-instructions --format claude-md
```

## Common patterns

### Pattern: "Get a second opinion on this design"

You're chatting with Claude Code in your project session.  You hit a non-trivial decision.  Tell Claude Code:

> Get a second opinion on whether we should use sqlite or postgres for this side project.  Make sure to look at the harness ask output's packet.md for synthesis.

If your CLAUDE.md has the agent-instructions, Claude Code will:
1. Run `python -m harness ask "should this side-project use sqlite or postgres? trade-offs?"`
2. Read the resulting `coord/reviews/ask-<ts>/packet.md`
3. Synthesize the 3 engines' perspectives for you

### Pattern: "Ship-critical decision needs DeepSeek v4-pro audit"

> Use `python -m harness engines recommend audit` to pick the audit engine, then run `harness ask` with that engine + model override on the decision below.

The agent will:
1. Run the recommender, see it returns `deepseek-via-claude` with `model_override: deepseek-v4-pro`
2. Run `python -m harness ask "..." --engines deepseek-via-claude` with the audit settings
3. Show you the result

### Pattern: "Fresh agent, no setup"

If you give the project to someone else:

1. They follow [`docs/HANDOFF.md`](HANDOFF.md) for first-time setup
2. After setup, they run `python -m harness agent-instructions --format claude-md >> ~/.claude/CLAUDE.md` to make it discoverable everywhere
3. From then on, every Claude Code session they start, anywhere, knows the harness exists

## Limitations + edge cases

- **Multiple Python environments**: if the operator uses different venvs for different projects, `pip install -e .` only registers the harness in ONE venv.  In other venvs, `python -m harness` won't work.  Solutions:
  - Always use the venv where harness was installed
  - Re-install in each venv (it's editable, so it points back at the same repo)
  - Or use the global Python (`/usr/bin/python` or Windows Store Python) for harness invocations
- **Multiple machines**: each machine needs its own clone + install + key configuration.  The state in `.env` + `coord/key_health.jsonl` does NOT auto-sync across machines.  Backup options:
  - Commit a redacted `.env.example` (already shipped)
  - Use a private gist or vault for actual keys
  - Re-run `python -m harness keys serve` on each new machine
- **Renaming or moving the repo**: the egg-link points at the install path.  If you move the harness repo, re-run `pip install -e .` to refresh the link.

## When the harness install moves or breaks

```bash
python -m harness doctor
```

Will surface any path or environment issues.  Then:

```bash
cd <harness-repo>
pip install -e . --force-reinstall
```

Re-establishes the egg-link.

---

## Related docs

- [`HANDOFF.md`](HANDOFF.md) — sharing kit for giving the harness to someone else
- [`OPERATOR_QUICKSTART.md`](OPERATOR_QUICKSTART.md) — first-time install
- [`HARNESS_VISUAL_MANUAL.md`](HARNESS_VISUAL_MANUAL.md) — what each command looks like
- [`INTERNAL_OPERATOR_RUNBOOK.md`](INTERNAL_OPERATOR_RUNBOOK.md) — daily-ops procedures (key rotation, recovery)
