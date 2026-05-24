# Operator runbook — daily playbook

This page is for the **non-technical operator** running xaxiu-harness
day-to-day.  If you can edit YAML, run a command in a terminal, and
read a CSV file, you're set.  You will NOT need to write or read
Python.

If something below doesn't match what you're seeing on your machine,
your engineering teammate has changed something — ask them.

---

## Morning sequence — 3 commands

Every morning, run these three commands in the harness directory.
That's it.

```powershell
cd D:\xaxiu-harness-standalone
harness preflight
harness morning-brief
```

### What each does

| Command | What you see | If it complains |
|---|---|---|
| `harness preflight` | Green checks (`[OK]`) for the engines, observer, loops, git, pytest cache, dead engines | Run `harness preflight --fix` (see below) |
| `harness morning-brief` | Overnight activity summary, what shipped, what's in the queue | If empty: nothing happened overnight — that's fine |

If `harness preflight` shows all `[OK]` (or only `[!]` warnings),
you're good for the day.

If it shows `[X]` (fail), follow the **Recovery** section below.

---

## When preflight shows `[X]` — recovery

The harness has a single command that fixes the three most common
problems automatically:

```powershell
harness preflight --fix
```

This handles:

1. **`[X] git_clean`** — you have modified files that haven't been
   committed.  `--fix` runs `git stash`, which sets them aside.  You
   can get them back later with `git stash pop` (the harness will
   remind you).
2. **`[X] pytest_cache`** — leftover from someone's testing.  `--fix`
   clears it; pytest will rebuild on its next run.
3. **`[!] dead_engines`** — one of the LLM engines stopped working
   (key revoked, endpoint changed, rate limit).  `--fix` quarantines
   the bad engine so the harness routes around it.  You can reset it
   later with `harness engines reset <engine-name>` once your
   engineering teammate has fixed the root cause.

**Always preview first**:

```powershell
harness preflight --fix --dry-run
```

This shows exactly what `--fix` would do — no changes applied.
Re-run without `--dry-run` once you're happy with the preview.

---

## When something looks weird

These three commands answer "what's the harness doing?":

```powershell
harness morning-brief --since-hours 12   # last 12h activity
harness queue list                        # what's queued for the loop
harness observer flags                    # any escalations needing attention
```

If `harness observer flags` shows a HIGH severity flag, that's the
harness asking for help.  Read the message; if it's not obvious,
ask your engineering teammate — but **always** include the
output of `harness panic-dump` so they have full context (it's
secret-scrubbed automatically; safe to share).

---

## When you want to see the dashboard

```powershell
harness dashboard-serve
```

Opens at `http://127.0.0.1:7878` in your browser.  Shows the loop
heartbeat, current dispatches, observer flags, engine health, and
recent runs.  Refresh-free (auto-updates via WebSocket).

Close the terminal to stop the dashboard.

---

## When the autonomous loop is supposed to be running

```powershell
harness heartbeat show
```

Should print a recent timestamp and the current active dispatch.
If the timestamp is more than 1 hour old, the loop is dead.

To restart:

```powershell
harness start --orchestrator mimo --mode autonomous
```

The `--mode autonomous` flag will run `harness preflight` first.
If preflight has `[X]` failures, the start command will refuse;
fix them first (see Recovery above), then re-run.

---

## What you should NOT do (without asking)

| Action | Why |
|---|---|
| Run `git commit` or `git push` yourself | The harness creates commits as part of the loop; manual commits can confuse it |
| Edit files under `src/harness/` | This is Python source code; the loop manages it |
| Edit `coord/STATUS.csv` directly | The loop writes this; manual edits can be overwritten |
| Delete files under `runs/` | These are evidence files for past dispatches; the loop may still reference them |
| Stop the dashboard while a dispatch is running | The dashboard reads state; a running loop is fine without it but you lose visibility |

Things you CAN edit safely:

- `adapters/<your-project>/adapter.yaml` — your project's config
- `spec/auto/*.md` — your queued task specs
- Anything under `docs/`

---

## When you need to escalate

If you see any of these, **stop and ask your engineering teammate**:

- `L5` anywhere in an error message (this is the harness's
  "fatal" tag; only operator action can fix it)
- A Python traceback (lines starting with `File "...", line ...`)
- `harness preflight --fix` returning `[X]` with an error message
- The dashboard at 7878 is unreachable AND `harness heartbeat show`
  shows no recent timestamp

When you escalate, run this once and share the output:

```powershell
harness panic-dump --target-dir .
```

This bundles up the harness's state (with secrets scrubbed) into a
single `.tar.gz` file your teammate can use to debug.

---

## Glossary

| Term | What it means |
|---|---|
| **Engine** | An LLM backend — DeepSeek, Kimi, MiMo, Anthropic, Gemini |
| **Dispatch** | One call to an engine to do a task |
| **Worker** | A subprocess that runs one task in an isolated git worktree |
| **Run** | A coordinated set of workers handling one spec |
| **Wave** | A planned batch of features (W6, W7, W8...) |
| **Preflight** | The pre-flight readiness check (like an aircraft checklist) |
| **Audit** | A MiMo review of a shipped feature against its spec |
| **Observer** | A background task that watches the loop and flags issues |
| **L5** | The harness's "fatal — operator action required" severity |

---

## Files you'll touch often

- `coord/STATUS.csv` — task tracker; one row per task with status
- `coord/morning-brief-*.md` — daily summaries (auto-generated)
- `coord/reviews/audits/*.md` — MiMo audit reports
- `coord/observer/flags/*.md` — observer escalations

---

## Last-resort commands

If everything's broken and the dashboard won't come up:

```powershell
harness doctor          # checks install
harness preflight       # checks runtime readiness
harness panic-dump      # creates a debug bundle
```

Send the panic-dump to your engineering teammate, then go get coffee.
They'll either fix it or tell you what to do next.
