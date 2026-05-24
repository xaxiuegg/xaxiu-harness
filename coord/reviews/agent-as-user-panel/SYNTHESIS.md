# Agent-as-natural-user validation panel — synthesis

_Dispatched: 5 reviewers, elapsed 32s_

## A1-fresh-clone-walkthrough  (deepseek/deepseek-v4-flash)

**Headline verdict** — YES-IF: the harness is structurally well-suited for an agentic coding agent, but only after 3 targeted simplifications remove the first-30-minute walls a human CLI user would never hit.

**Strongest evidence FOR the hypothesis**  
- The harness’s CLI is entirely composable (`harness init`, `harness dispatch`, `harness adapter`), exactly the kind of deterministic, side-effect‑clean interface a code‑generating agent can script without guessing at UI states.  
- The agent reads `CLAUSE.md`, `dispatch-rules.md`, and `STATUS.csv` natively — the harness’s scaffolding is already the agent’s *native configuration language*, not a human‑friendly wizard.  
- DPAPI secrets, engine registration, and cost ledger are all file‑based or DB‑based, so an agent can create, inspect, and mutate them with `exec()` or `subprocess.run()`.  
- The existing spec files (`spec/operator-modes.md`, `spec/status-tracker.md`) are already written for a technical reader; an agent can parse them instantly.

**Strongest evidence AGAINST**  
- **First‑run friction chain:** The agent would clone, then `python -m harness init`, then immediately get an `EngineNotConfigured` error because it hasn’t set env vars for the target engine. A human dev would go read `.env.example`, but the agent has to discover that file exists, then figure out which engines are even available. The agent’s natural next command (`harness env –help`) shows a grid that doesn’t map to the *other* project’s config.  
- **No bootstrap‑target abstraction:** The agent, after cloning into a fresh scraper project, has to manually adjust every path – adapter YAML location, JSONL output directory, dashboard port. The harness assumes you are building *inside* the harness repo, not importing it as a library. A human would tolerate poking around, but an agent wants a single `harness init --target=/path/to/scraper` that writes a minimal `harness.yaml` relative to the target project.  
- **Loop start requires a running coordinator or observer.** The agent’s plan “add multi‑engine dispatch + audit” can’t start with `harness loop start` – that command expects a pre‑existing loop file and an active state DB. The agent hits a silent failure unless it first runs `harness init` then `harness loop init`, which is undocumented in the top‑level help.

**The 3 most important W11 changes**  
1. **Add `harness init --target`** that generates a minimal `harness.yaml` in the *other* project, creates a `.harness/` state directory there, and prints the one‑line command to start the default loop. This is the single 10‑second command an agent can issue from outside the repo.  
2. **Create a `harness bootstrap`** verb that does in one call: installs dependencies, checks for `ENGINE_API_*` env vars (prompting for missing ones via stdin if interactive), runs the preflight doctor, and starts the observer in background. The agent can then say `harness bootstrap` and get a fully armed project.  
3. **Eliminate the launch‑order dependency for `loop start`** – make it auto‑init if no loop file exists, using sensible defaults that the agent can override via flags. The agent shouldn’t need to read `loop init –help` to discover the 4‑step incantation.

**Single‑sentence recommendation** — Pivot to dual‑target but invest the W11 sprint on the 3 bootstrap‑day simplifications above; the agentic‑coding‑agent path is real but demands a 10‑second onboarding experience, not a 10‑minute exploration.

---

## A2-adapter-onboarding  (deepseek/deepseek-v4-flash)

**1. Headline verdict**  
YES-IF — the adapter format and NL→YAML generation are promising for agent onboarding, but several friction points must be resolved before the path is frictionless.

**2. Strongest evidence FOR**  
- The `adapter from-description` verb directly mirrors how an agent works: read a one‑paragraph project description and produce a structured YAML adapter. This replaces manual schema study and reduces the designer’s cognitive load to one tool call.  
- Adapter YAML is a single declarative file covering engine routing, fallback chains, status fields, and provider config. Agents excel at parsing and generating such structured documents.  
- The included sample adapters (`spec/`) and the CLI help give agents enough context to produce correct output without reading the full source, matching the “copy‑paste‑and‑adjust” pattern they favour.

**3. Strongest evidence AGAINST**  
- The YAML schema is *not* self‑explanatory from a quick read—nested keys like `provided_rules`, `inter_data_dependencies`, and `pass_condition` require domain knowledge that an agent may not possess without scanning the full adapter loader source or error messages.  
- NL→YAML generation often produces structurally valid but semantically weak adapters (e.g., missing required fallback chains, over‑generalised routing). The human designer can iterate; an agent that blindly trusts the output will fail silently until runtime.  
- The validation CLI (`adapter validate`) exists but its messages are designed for human eyes, not agentic parsing—there is no machine‑readable error JSON or structured feedback loop for automatic correction.

**4. The 3 most important W11 changes**  
1. **Add `adapter validate --json`** that outputs structured validation errors (reason, path, severity). This lets agents auto‑correct adapters in a loop without interpreting free‑text messages.  
2. **Ship a “minimum viable adapter” template** with only the required keys and comments. Current samples show too many optional fields; an agent copying those may over‑engineer or miss critical links.  
3. **Provide a `adapter bootstrap` command** that runs `from-description`, validates, shows a diff, and optionally writes the adapter—all in one agent‑callable workflow. Combine with a hard pre‑run test that verifies the adapter works against the local engine pool.

**5. Single-sentence recommendation**  
Pivot to dual‑target by W11: optimise the adapter pipeline for agent automation (structured feedback, minimal template, bootstrap command) while keeping the human‑friendly NL path as a fallback.

---

## A3-competing-tools  (mimo/mimo-v2.5-pro)

1. **Headline verdict:** YES-IF — the hypothesis holds conditionally, but only if the install/adapter cost drops below one agent tool-call threshold and the unique bundled primitives are actually better than what an agent can compose from first-class SDKs.

2. **Strongest evidence FOR:** The five primitives bundled together (audit gate + mutation canary + proxy circuit-breaker + STATUS.csv + observer cycle) represent ~20-40h of non-trivial scaffolding that an agent would otherwise have to design, implement, and debug across projects. A single `harness init` → adapter YAML → `dispatch` pipeline gives the agent a battle-tested decision-replay, cost-ledger, and fallback-chain out of the box. An agent reading CLAUDE.md + dispatch-rules.md + memory files natively is genuinely the ideal consumer — no onboarding friction, no "where do I put this?" confusion. The coordinator/planner architecture maps well to how agents already decompose tasks.

3. **Strongest evidence AGAINST:** The agent has *better native alternatives* for most components individually. Claude Code's native memory system + hooks replaces STATUS.csv + observer cycle. Aider's model-rotation config replaces the proxy with zero install. LangGraph's `StateGraph` gives proper multi-agent orchestration without a CLI abstraction layer. The harness forces YAML adapter authoring — an agent can generate this, but it's a friction point where the agent might ask "why not just write `httpx` calls in 30 lines?" The DPAPI dependency is Windows-specific and hostile to containerized/sandboxed agent environments. The biggest threat: Cursor + Claude Code are *converging* on built-in multi-model routing, making the proxy layer a diminishing moat.

4. **Three most important W11 changes:**
   - **Zero-adapter bootstrap mode**: `harness init` should generate a fully working `dispatch` pipeline with zero YAML editing — a sensible default adapter that the agent can refine later, not one it must author first.
   - **Kill DPAPI, embrace environment-variable-first secrets**: Agents run in containers, CI, and sandboxes. Make `env` the primary path, DPAPI optional.
   - **Ship as a Python library, not just CLI**: An agent will `pip install xaxiu-harness` and import `from harness import dispatch, Coordinator` in code far more naturally than shelling out to `python -m harness dispatch`. The CLI is for humans; the API is for agents.

5. **Single-sentence recommendation:** Pivot — reposition as a **pip-installable SDK** with zero-config defaults, because the agent-to-agent use case is real but the current CLI+YAML+DPAPI surface area makes the agent likely to just compose LangGraph + httpx instead.

---

## A4-friction-inventory  (deepseek/deepseek-v4-flash)

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

---

## A5-w11-reframe  (mimo/mimo-v2.5-pro)

**YES-IF** — the hypothesis holds, but only if you ruthlessly prune the operator-first UX that W10 layered on and rebuild the entry point for agents.

---

**Strongest evidence FOR:**
The harness's core primitives are *exactly* what agents build from scratch every project: routing logic, cost tracking, audit gates, canary patterns. The 20-40h scaffolding estimate is real. Agents reading CLAUDE.md natively solves the "documentation problem" that kills human adoption. The YAML adapter pattern (declarative routing) is agent-tooling 101. STATUS.csv as coordination primitive is something an agent would invent but doesn't have to.

**Strongest evidence AGAINST:**
The CLI surface area is hostile to agents — 22 verbs, 60+ subcommands, 8 global flags. Agents optimize for *tool calls*, not *argument parsing*. DPAPI is Windows-only; agents run on Linux containers. The current CLAUDE.md is enormous (3000+ chars) and describes a *system*, not a *workflow*. An agent cloning this repo needs to know "dispatch this packet" not "here's the full architecture."

---

**3 most important W11 changes for agent-first:**

1. **Smaller CLAUDE.md template** — 800 chars max. Three sections: (a) what this does, (b) the 3 commands you'll use, (c) how adapters work. Everything else moves to `/spec/`.

2. **Cross-platform secret management** — Replace DPAPI with environment variables + `.env` file fallback. Agents set `ANTHROPIC_API_KEY` in their shell; they don't have DPAPI stores. The `env-wizard` verb becomes `env init` that writes a `.env` template.

3. **Agent-friendly quickstart** — `clone → pip install → harness adapter generate "route Kimi for code, Claude for review" → harness dispatch test` in under 4 tool calls. Current flow requires reading docs.

---

**W11 rows that become LESS important:**
- **Installer/GUI** — agents don't use installers or GUIs
- **Morning email** — agents don't read email
- **Operator-friendly daily verb** — that's for humans with runbooks
- **Dashboard** — nice to have, not agent-critical

**New W11 rows that surface:**
| Priority | Row | Rationale |
|----------|-----|-----------|
| P0 | `harness agent init` | One command: generate `.env`, starter adapter, minimal CLAUDE.md |
| P0 | Replace DPAPI with env-var-first secrets | Agents are cross-platform |
| P1 | `harness dispatch --dry-run` default | Agents want to test routing before committing |
| P1 | Programmatic Python API (not just CLI) | `from harness import dispatch; dispatch(packet)` is agent-native |
| P2 | Agent-optimized CLAUDE.md templates | Per-project-type templates, not one-size-fits-all |
| P2 | `harness adapter generate` with NL input | "Route code to Kimi, reviews to Claude" → YAML |

---

**Does the wave count drop from 6 to 2-3?**
**Yes.** If you commit to agent-first, W11 collapses to:

1. **W11-A: Agent entry point** — `agent init`, env-var secrets, minimal CLAUDE.md
2. **W11-B: Programmatic API** — Python module import alongside CLI
3. **W11-C: Adapter UX** — NL→YAML generation, validation, `--dry-run` default

That's it. Three focused waves. The dashboard, email, GUI, installer — those are W15+ for the *human* operator who inherits an agent-built project. The agent doesn't need them.

---

**Single-sentence recommendation:**
**Pivot** — reframe W11 as "agents clone and use in 4 tool calls" and ship the three waves above; keep human-operator UX as a separate track that builds *on top of* agent-first primitives.

---
