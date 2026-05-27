# Handing xaxiu-harness to a new user

This document is for **the person sharing the harness with someone new**.  It contains:

1. **What to send them** (one URL + one message + one prompt)
2. **What they should expect** (the workflow on their side)
3. **The exact setup prompt** to paste into their Claude Code session
4. **How they trigger / use the harness afterwards**

Total recipient time: **15-25 minutes** if they already have Python + Claude Code + at least one provider account.  Up to ~60 minutes if they need to sign up for provider accounts.

---

## Part 1 — What you send them

Three pieces.  Paste them into a message, an email, or a chat.

### Piece A: the repo URL

```
https://github.com/xaxiuegg/xaxiu-harness
```

### Piece B: a short orientation message

```
xaxiu-harness is a personal tool that lets you ask 3 AI models the same question
in parallel from your shell, then compare their answers.  Runs entirely on your
laptop, no server.

You'll need: Python 3.11+, Git, Claude Code CLI (https://docs.claude.com/en/docs/claude-code/setup),
and at least one provider API key (Kimi, MiMo, or DeepSeek work; the keys UI will
walk you through getting whichever ones you want).

Setup: clone the repo, open Claude Code in that directory, paste the prompt below.
Claude Code will guide you through the rest in 15-25 minutes.

Once it's set up, your daily-driver command is:
    python -m harness ask "your question here"

That fires 3 engines in parallel and saves all 3 responses for you to compare.
Typical cost is $0.20-0.30 per panel.

When you're ready, paste this into Claude Code (with the harness repo as your
working directory):
```

### Piece C: the Claude Code setup prompt

```text
Set up xaxiu-harness on this machine for me.  Do these steps in order, stopping
to ask me if anything fails or needs my input:

1. Read CLAUDE.md and docs/OPERATOR_GUIDE.md for context on what this is.

2. Check my prerequisites:
   - Python 3.11+ installed (`python --version`)
   - Git installed (`git --version`)
   - Claude Code CLI installed (`claude --version`)
   If any are missing, tell me what to install and stop.

3. Install the harness package: `pip install -e .` from the repo root.
   Confirm by running `python -m harness --help` and showing me the verb list.

4. Run `python -m harness doctor` and show me the 9-check traffic-light output.
   If any check is red, walk me through fixing it before continuing.

5. API keys.  Look at step 4's `engine_keys` check (P2 audit fix
   2026-05-27 consolidated the old `secrets` + `engine_reachability`
   + `env_var_inventory` checks into one).

   IF it was green (I already have at least one provider key configured):
       Skip to step 7.  Just tell me which key(s) you saw + that we're moving on.

   IF it was red or yellow:
       Run `python -m harness keys serve --no-open`.
       Print the URL it shows + tell me to open it in my browser.
       Wait for me to confirm I've pasted my keys, clicked Test on each
       (live API probe — should turn the row green), and clicked
       Save all to .env.

6. After keys are saved (or if you skipped step 5), re-run
   `python -m harness doctor` to verify the keys check is now green.
   If it isn't, walk me through which key is missing or wrong.

7. Run one verification dispatch:
   `python -m harness ask "Reply with the single word OK." --engines mimo-via-claude --no-save --max-budget-usd 0.05`
   We should see "OK" in the response.  If it fails, look at the error and
   tell me what's most likely wrong (usually: bad API key, expired Claude Code
   auth, or no MiMo key configured — try a different --engines value if so).

8. Ask me: "Do you want the harness available in ALL future Claude Code
   sessions on this machine?  This appends a section to ~/.claude/CLAUDE.md
   so every Claude Code session — in any project directory — knows the
   harness is installed and how to use it.  Idempotent + uninstallable."
   If I say yes: `python -m harness install-agent-instructions`
   If I say no or "ask again later", skip — I can run it manually anytime
   (or `--uninstall` to remove later).

9. Ask me: "There's an optional sibling project called xaxiu-swarm that
   adds agentic multi-file dispatch (multi-turn tool use, in-place file
   edits across many files).  You DON'T need it for `harness ask`,
   `harness doctor`, or single-shot Pattern B engines — those work
   entirely from this repo.  You'd only want xaxiu-swarm if you plan to
   do agentic coding tasks (multi-file refactors, swarm-style fanout).
   Do you want to clone it now? [y/N]"

   IF I say yes:
     Clone it next to xaxiu-harness:
       git clone https://github.com/xaxiuegg/xaxiu-swarm.git
       cd xaxiu-swarm && pip install -e .
     Verify by running: `xaxiu-swarm backends`
     Should list: claude, claude-deepseek, claude-kimi, claude-mimo,
     deepseek, kimi, kimi-api, qwen

   IF I say no:
     Skip cleanly.  Tell me I can clone it later if I change my mind —
     instructions are in docs/HANDOFF.md § "Optional add-on".

10. When everything succeeds, tell me:
   - The harness is set up and working
   - The 4 most useful commands I should know:
       * python -m harness ask "..."       (your daily driver)
       * python -m harness keys serve      (manage keys via browser)
       * python -m harness doctor          (verify health)
       * python -m harness engines recommend <task-class>  (pick right engine)
   - Where outputs land: coord/reviews/ask-<timestamp>-<slug>/
   - That docs/OPERATOR_GUIDE.md § 2 has the screenshot walkthrough
   - That docs/OPERATOR_GUIDE.md § 4 explains using the harness
     from any project directory

CRITICAL: do NOT try to "fix" failures by running arbitrary commands or editing
my .env / configuration files.  Tell me the error, suggest the most likely
cause, and let me decide.  My machine is not a sandbox.
```

---

## Part 2 — What the recipient does

(You can also share this section with them, or trust the prompt to handle it.)

### Step 1: Install prerequisites (if they don't already have them)

| Tool | Get it from |
|---|---|
| Python 3.11+ | https://www.python.org/downloads/ |
| Git | https://git-scm.com/downloads |
| Claude Code CLI | https://docs.claude.com/en/docs/claude-code/setup |

### Step 2: Clone the repo

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
```

### Step 3: Open Claude Code in this directory

In the terminal, run:

```bash
claude
```

This drops you into an interactive Claude Code session **rooted in the harness repo**.  It can read the local files, run shell commands, and edit if you ask.

### Step 4: Paste the setup prompt (Piece C above)

Claude Code will:
1. Check your prerequisites
2. Install the harness via `pip install -e .`
3. Run `harness doctor` to surface any environment issues
4. Launch `harness keys serve` to give you a browser form for pasting API keys
5. Verify a real dispatch works
6. Tell you the 3 commands you'll use day-to-day

If any step fails, Claude Code will ASK YOU rather than guess.  Read the error, decide what to do, and resume.

### Step 5: Get at least one provider key

If you don't already have one, sign up for any of:

| Provider | Signup | Why pick this one |
|---|---|---|
| **MiMo (Xiaomi)** | https://mimo.xiaomi.com/ | Cheapest by far — $50 Token Plan gives ~6,200 panels/month |
| **DeepSeek** | https://platform.deepseek.com/ | Fastest at high concurrency; PAYG |
| **Kimi (Moonshot)** | https://platform.moonshot.cn/ | Subscription via Kimi Code; English-language interface |

You only need ONE key to get started.  The harness handles missing engines gracefully.

---

## Part 3 — Daily use after setup

Once Claude Code says setup is complete, the recipient's daily-driver commands:

```bash
# Ask 3 engines the same question, compare answers
python -m harness ask "should I learn Rust or Zig next?"

# See current key + health status
python -m harness keys list

# Add/rotate keys via browser form
python -m harness keys serve

# Confirm everything is healthy
python -m harness doctor
```

### Where outputs live

Every `harness ask` creates a timestamped directory under `coord/reviews/`:

```
coord/reviews/ask-20260526-150035-should-i-learn-rust-or-zig-next/
├── question.md                  # what you asked
├── kimi-via-claude.md           # Kimi's answer
├── mimo-via-claude.md           # MiMo's answer
├── deepseek-via-claude.md       # DeepSeek's answer
├── packet.md                    # all 3 concatenated (synthesis-ready)
└── summary.json                 # cost / latency / metadata
```

The recipient can either read the per-engine files manually or hand `packet.md` to a fresh Claude Code session for synthesis.

### When something breaks

Tell the recipient: paste this into Claude Code:

```text
Run python -m harness doctor.  Tell me which check is red or yellow and what
the most likely fix is.  Don't run any fix commands yet — just tell me what
to do.
```

Or for engine-specific issues:

```text
Run python -m harness engines health, then python -m harness engines failures.
Tell me which engine is failing and what category (auth / quota / network /
unknown).  Suggest the next step.
```

---

## Part 4 — What you (the sharer) might be asked

After they've used it for a bit, the recipient might come back with questions.  Pre-empt them:

| Question | Short answer |
|---|---|
| "How do I update?" | `cd xaxiu-harness && git pull && pip install -e .` |
| "Can I use a key from a provider that's not in the list?" | The harness supports 7 providers out of the box.  Adding a new one is a code change; ask. |
| "Is it safe to commit my .env?" | No.  `.env` is in `.gitignore` already; double-check before committing. |
| "How do I make a backup of my setup?" | The keys live in `.env`; per-machine state lives in `~/.harness/` and `coord/key_health.jsonl`.  Back those up if you care. |
| "How do I uninstall?" | `pip uninstall xaxiu-harness && rm -rf .venv ~/.harness/`.  The repo dir can be `rm -rf`'d like any other. |
| "Where's the documentation?" | Three docs cover most needs: README.md (overview), docs/OPERATOR_GUIDE.md (everything operator-facing including setup, daily commands, and recovery), docs/AGENT_REFERENCE.md (for AIs using the harness as a sub-tool). |

---

## Optional add-on: the sibling repo (xaxiu-swarm)

Only mention this if the recipient asks about multi-file refactors or batch agent dispatch.

```text
There's a sibling project called xaxiu-swarm (https://github.com/xaxiuegg/xaxiu-swarm)
that adds agentic dispatch — multi-file edits, multi-turn tool use.  You don't
need it for `harness ask` to work; it's only relevant if you want to fire
agents at coding tasks.

If they want it later:
   git clone https://github.com/xaxiuegg/xaxiu-swarm.git
   cd xaxiu-swarm && pip install -e .
   xaxiu-swarm backends   # should list claude-mimo, claude-kimi, claude-deepseek + legacy
```

---

## Appendix: this handoff doc itself

This file is designed to be self-contained — you can copy the URL + Piece B + Piece C from § Part 1 and paste them into a Slack DM, email, or chat.  The recipient doesn't need to open this document to succeed; their Claude Code session reads the in-repo docs (CLAUDE.md, OPERATOR_GUIDE.md) and walks them through the rest.

Updated: 2026-05-26.  If you change `harness setup`, `harness keys serve`, or `harness ask` significantly, also update Part 3 here.
