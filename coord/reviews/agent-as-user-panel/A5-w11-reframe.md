<!-- persona=A5-w11-reframe status=OK (31515ms) -->

# A5-w11-reframe

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
