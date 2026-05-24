<!-- persona=A4-friction-inventory status=OK (20673ms) -->

# A4-friction-inventory

**1. Headline verdict**  
YES-IF — the harness is architecturally suited to agentic coding agents, but only if W11 addresses four hard friction points that currently block a “clone and run” experience on non-Windows platforms and for agents unfamiliar with its internal conventions.

**2. Strongest evidence FOR the hypothesis**  
- The harness’s own CLI + environment checks (`doctor`, `env-wizard`) automate the setup steps a human would struggle with.  
- Its adapter/coord abstractions and fallback chains mirror an agent’s mental model: “I need a plan → dispatch to the best engine → retry on failure → record decision.”  
- STATUS.csv, audit gates, canaries are exactly the scaffolding an agent must build from scratch; the harness provides them as ready-made primitives.  
- The code is heavily instrumented (packet envelopes, replay, heartbeat) — agents read structured logs faster than humans read prose.

**3. Strongest evidence AGAINST**  
- **DPAPI secrets** (Windows‑only) break on Mac/Linux with no fallback — agent will error on `doctor` and have no graceful path.  
- **30‑verb CLI** forces agents to parse complex help trees; a naïve agent may try `harness` without a subcommand and get a huge wall of text.  
- **Multi‑agent v2 vs adapter v1** ambiguity confuses an agent that needs to decide which mode to use — no single entry point says “start here.”  
- **Memory files** must be manually created and populated; agents expect a convention but the harness doesn’t auto‑bootstrap them.

**4. The three most important W11 changes**  

1. **Cross‑platform secrets** – Replace Windows DPAPI with a portable encrypted file (e.g., AES‑GCM + key derived from a machine‑specific token). Agent clones on Linux should work without finding a Windows machine.  
2. **Quick‑start cheat‑sheet** – Add `harness quickstart` that runs `doctor`, seeds a `.env` template, creates a dummy STATUS.csv, and prints a three‑command “hello world” workflow. Reduce cognitive load to two lines: `harness quickstart` then `harness dispatch "explain this project"`.  
3. **Auto‑bootstrap agent‑specific scaffolding** – `harness init` should optionally create a `CLAUDE.md` snippet, a memory directory, and a `.cursorrules` file that teaches the agent the harness’s core verbs and when to use coord vs adapter.  

**5. Single‑sentence recommendation**  
Pivot to **dual‑target**: keep the human‑friendly UX but add a first‑class “agent onboarding” path (quickstart + cross‑platform secrets + scaffolding generator) that makes clones productive in under five minutes.

---

### Friction inventory (every concrete point an agent would hit in the first hour)

| Friction | Agent impact | Real or “read docs”? |
|----------|--------------|----------------------|
| **Windows DPAPI** – `dpapi.py` fails on macOS/Linux | Agent cannot store secrets; `doctor` reports DPAPI missing. Even if it skips, secrets workflow broken. | **Real** – no fallback, no error message pointing to a workaround. |
| **30‑verb CLI** – `harness --help` dumps 20+ commands + 7 operator flags | Agent wastes time scanning, may pick wrong verb first (e.g., `coord` instead of `dispatch`). | **Real** – overwhelming for a first‑time agent; needs a “most common” filter. |
| **Ambiguous entry point** – `adapter` vs `coord` vs `dispatch` | Agent doesn’t know if it should set up an adapter or go straight to coord v2. `dispatch` works without an adapter, but that’s undocumented. | **Real** – no authoritative “start here” doc for agents. |
| **STATUS.csv ownership** – harness uses its own STATUS.csv for task tracking, but the project may already have one | Agent may overwrite or double‑track. Format conflict if project uses different columns. | **Real** – harness assumes sole ownership. |
| **Memory file pattern** – `~/.claude/projects/.../memory/` must be manually created | Agent gets no memory on fresh clone; cannot store per‑project sessions. | **Real** – no `harness init` creates these. |
| **Operator‑mode flags** – `--mode`, `--escalation-threshold`, etc. are passed as CLI flags but also YAML keys | Agent unsure which takes precedence; confusion between YAML config and CLI override. | **“Read docs”** (the spec explains it, but it’s easy to miss). |
| **Engine fill / cooldown** semantics – agent may need to manually heal engines (`engines-heal`) | A fresh clone has no engines configured; `dispatch` returns “no engine available” with a cryptic message. | **Real** – `doctor` should detect empty engine pool and suggest configuration. |
| **Windows Task Scheduler dependency** for observer | Agent on Linux can’t run observer; docs say “use cron” but no example. | **Real** – no cross‑platform observer support. |
| **`coord run` schema** – requires a worktree and plan file; agent must understand planner flow | High barrier for first use; agent would need to read `spec/multi-agent-harness-architecture.md` fully. | **“Read docs”** – but the doc is 15 pages, not a quick reference. |
| **No auto‑install** – `pip install -e .` works, but agent must know to run it | Trivial: any agent runs `pip install -e .` automatically. | **Low friction** – just an extra tool call. |
