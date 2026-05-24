<!-- persona=A1-fresh-clone-walkthrough status=OK (14900ms) -->

# A1-fresh-clone-walkthrough

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
