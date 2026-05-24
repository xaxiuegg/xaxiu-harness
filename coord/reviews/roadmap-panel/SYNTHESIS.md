# Chat-tier roadmap panel — synthesis

_Dispatched: 8 reviewers (DeepSeek primary + MiMo on creative lenses), elapsed 38s_

Each persona thinks from a distinct lens to surface convergent themes vs. dissents.  See `_state_snapshot.md` for the input.

## R1-feasibility-analyst  (deepseek/deepseek-v4-flash)

1. **Headline verdict**: YES-IF – the core dispatch, circuit-breaker, and cost-ledger architecture survives a chat-tier rewrite; the CLI and YAML surface are the only blockers, not the engine.

2. **Wave-count estimate**: 5 waves p50, 3–8 p90 (W11–W15/18). Building a conversational wrapper (Slack bot, local web chat, or embedded REPL) plus fixing the first-run gauntlet and adding natural-language intent parsing requires ~2 waves for scaffolding, 1 wave for DPAPI/Credential wizard, 1 wave for stateful session/idempotency, and 1 wave for polish + testing. The existing CLI subcommands become internal API endpoints.

3. **The 3 most load-bearing decisions in W11**:
   - **Define the conversational contract**: pick a single target interface (e.g., localhost web chat using FastAPI + WebSocket) and commit to it. This kills the CLI as the primary UX – all new features must be exposed via that interface first, CLI second.
   - **Rewrite `harness preflight` as a guided multi-step wizard** that outputs plain-language instructions, not PASS/FAIL verdicts. The current git-clean blocker must be replaced with an interactive “stash changes? (y/n)” or auto-stash with undo.
   - **Replace YAML config files with a single JSON blob persisted behind the conversation** (e.g., `profile.json` managed by the chat agent). Editing YAML is a non-negotiable showstopper for a ChatGPT-tier user; the chat interface must read/write config via natural language inference.

4. **The one thing to CUT or HIDE**: **All `harness status list` line-oriented output and `--recent` formatting**. A chat-tier user never wants to see a terminal table; that data must be surfaced as a single sentence (“Your latest run from 3h ago passed – cost $0.04, 5/5 tests green.”) or a minimal UI card. Hide the entire `harness status` subcommand behind a `/status` slash command that returns markdown.

5. **The one risk most likely to derail the trajectory**: **Ambiguity of intent parsing in a non-DSL conversation**. The existing dispatch layer expects structured commands (engine, model, fallback policy). If the chat interface misinterprets “run the audit again but cheaper” as “rerun with engine=gemini” instead of “rerun with max-cost-budget=$0.10”, the user gets unpredictable results and loses trust. Without a strict intent schema (e.g., slot-filling with confirmation), the system becomes worse than CLI.

6. **Single-sentence recommendation**: Go – but immediately pivot the W11+ roadmap from “polish CLI” to “build a conversational agent that wraps the existing engine layer, and treat the CLI as a debugging backdoor only.”

---

## R2-wave-estimator  (deepseek/deepseek-v4-flash)

**1. Headline verdict**  
YES-IF the operator executes a ruthless simplification of the first-run and daily surface before adding any new detection or coordination features.

**2. Wave-count estimate**  
6 waves (p50), 4–9 (p90). Current rate of ~1–2 weeks/wave holds, so 6–12 weeks to reach 7/10 for a user who can only type a single verb per day.

**3. Three load-bearing decisions for W11**  

1. **Kill the git_clean preflight blocker** by adding a `--force` or `--ignore-git` flag and a plain-English explanation when it fires (not a Python traceback).  
2. **Ship `harness start` as the single entry point** (combines wizard + first-run config + launch dashboard). Hide all other commands behind `--advanced` by default.  
3. **Default to dashboard-on-startup** (local FastAPI) and make `harness today` the fallback if dashboard fails – never expose the user to CLI error messages beyond a one-line status.

**4. One thing to CUT or HIDE**  
All 13 `coord` subcommands (plan/run/work/retry/integrate/replan…). A chat-tier user will never orchestrate multi-agent worktrees. Move them into a separate `harness coord --advanced` namespace or remove from the default install.

**5. The one risk most likely to derail the trajectory**  
Observer watchdog self-recovery lands with too many false positives (e.g., restarts on transient network blips) and appears as cryptic “ENGINE RESTARTED 3 TIMES” in the dashboard, destroying trust. The non-technical user cannot distinguish a real recovery from noise.

**6. Single-sentence recommendation**  
Go, but only if W11 is entirely dedicated to first-run simplification and hiding the 90% of commands that the target user will never touch – otherwise the harness remains a developer tool dressed in chat clothes.

**Stack-ranked wave plan (W11–W16)**  

| Wave | Theme | Example rows (3–5 per wave) |
|------|-------|-----------------------------|
| W11  | First-run zero-friction | fix git_clean blocker; `harness start` wizard; hide advanced verbs; default dashboard; one-line error output |
| W12  | Installer + observer reliability | standalone .exe/.msi; observer watchdog with clear user-facing messages; stop false restarts; CRLF stability |
| W13  | Default dashboard & cost surfacing | dashboard as default (no opt-in); cost-per-query widget; latency breakdown on first page |
| W14  | Morning brief & escalation | morning email brief (task-scheduler hook); L5 escalation output (plain text, no stack); `harness today` content rich |
| W15  | Mutation pattern expansion | async/await flips for observer/cycle; canary warm-tier update; silent-except baseline tightened |
| W16  | Polish & confidence | latency observability (time stats in `status list`); observer fragility hardening; final UX review with a non-technical user |

---

## R3-architect  (deepseek/deepseek-v4-flash)

**Headline verdict**  
YES‑IF the operator commits to a desktop chat app rather than bolting chat onto the CLI.

**Wave-count estimate**  
6 waves p50 (W11‑W16), confidence range 4‑10 waves (p90). First 3 waves are foundation (IPC, chat scaffold, first‑run wizard); next 3 polish and hide advanced verbs.

**The 3 most load‑bearing decisions in W11**

1. **Pick IPC mechanism** – REST over localhost (FastAPI auto‑started by Electron) is the only practical choice. Avoid stdin/stdout because the operator expects the Python backend to keep state across conversations. Commit to a single JSON‑based API contract for all verbs (`POST /chat {text}`, `GET /status`, etc.).

2. **Convert the 30+ verb CLI into a chat‑first command set** – Not all verbs become GUI buttons. Use a `*` precedence: the 5‑6 daily‑use verbs (today, morning‑brief, status list, preflight --fix, engines‑heal, harness daily) become one‑click buttons in the chat UI. The remaining 25+ verbs (coord subcommands, mutation, audit flags) are only accessible via typed chat commands, hidden behind a “/” prefix or a separate “advanced commands” panel.

3. **Build a first‑run wizard that replaces the broken preflight** – The `harness env-wizard` exists but is buried. In W11, create a single “Welcome” screen that checks git_clean, DPAPI, and Python venv, then walks the operator through fixing each issue with a one‑click action (e.g., “Commit your changes? [Yes] [Stash] [Show diff]”). The wizard must *succeed* every time, even if it means auto‑stashing or auto‑committing.

**The one thing to cut or hide**  
The entire `coord` pipeline (13 subcommands). A chat‑tier user never needs to see planner/worker/integrate. Hide behind a “/coord” chat command or a developer toggle. It adds visual noise and cognitive load.

**The one risk most likely to derail the trajectory**  
**Desktop app scope creep** – The operator may get tempted to add a dashboard, cost widget, email brief, etc. before the core chat loop works. Ship a minimal Electron shell with a single chat input box, a status bar (last preflight verdict), and the 5‑6 quick‑action buttons. Nothing else. Every new feature must be a chat‑driven command first, GUI second.

**Single‑sentence recommendation**  
Go – but force‑cut the coord subcommands and ship a bare‑bones Electron chat window in W11, then let the operator’s usage shape W12‑W16 buttons.

---

## R4-ruthless-pm  (mimo/mimo-v2.5-pro)

1. **YES-IF**, but only if the operator accepts that ~40% of what the harness currently ships needs to be hidden behind `--advanced` or outright deferred — the current surface is a developer platform wearing an operator hat.

2. **4 waves p50, 3-7 p90.** W11: installer + single-verb entry point. W12: hide/defer engineering verbs, consolidate surface to ~5 commands. W13: error translation (tracebacks → plain English). W14: polish + dashboard default. The velocity has been good — the bottleneck is willingness to cut, not technical debt.

3. **The 3 load-bearing W11 decisions:**

   **a. Ship a Windows installer (`.exe` or `.bat` + bundled venv) that replaces git-clone entirely.** The git_clean preflight blocker is a death sentence for a chat-tier user. No installer = no path to 7/10, full stop. Even a self-extracting zip with a double-click `install.bat` that does `python -m venv`, `pip install .`, and `harness env-wizard` would close this gap.

   **b. Define `harness ask "..."` as THE default surface** — a single verb that routes to the best available engine, runs a soft preflight silently, and returns a plain-text answer. Today a chat-tier user has to understand engines, preflight, profiles, and dispatch. They shouldn't need to know any of that exists. `harness ask` should be the *only* thing documented on the README's first page.

   **c. Consolidate to 5 operator-facing verbs: `ask`, `daily`, `today`, `status`, `help`.** Everything else — `engines-heal`, `preflight`, `env-wizard`, `profile set`, `status list --recent` — gets folded into `daily`'s morning routine or hidden behind `--advanced`. The current 12+ verb surface is a tax on working memory that a chat-tier user will never pay.

4. **CUT: `harness engines-heal` as a standalone verb.** A chat-tier user will never diagnose engine health manually. Fold its logic into the circuit-breaker auto-fallback that already exists — engines *should* heal themselves. Exposing a manual heal verb signals to the user that the system is fragile and they're responsible for fixing it. That's the opposite of the trust model you need.

5. **Feature-count creep masquerading as progress.** W1–W10 added capabilities at a rate of ~1.5 new verbs or flags per wave. Each one feels small in isolation, but the cumulative surface is now a ~30-item mental model. If W11–W14 *add* the queued items (cost widget, morning email, L5 contract, dashboard default) without *removing* or hiding an equal number, the chat-tier user's experience degrades even as the feature list grows. The risk is that the operator treats the backlog as a queue to drain rather than a portfolio to cut.

6. **Go — but freeze all new features for one wave and hide half the existing ones.** The harness has the right engine underneath; it just needs a ruthlessly thin skin on top.

---

## R5-competitive-bar  (deepseek/deepseek-v4-flash)

## Competitive-Landscape Review

### 1. Headline Verdict
**NEEDS-PIVOT** — as a CLI‑only tool with YAML config, the harness cannot reach 7/10 for a ChatGPT‑tier user without a fundamental shift to a GUI‑first experience.

### 2. Wave-Count Estimate
8 waves P50, 5–12 P90. The first 3 waves must be spent exclusively on replacing the CLI surface with a default web dashboard + one‑click installer, or the gap only widens.

### 3. Three Load-Bearing Decisions (W11)

1. **Default to the FastAPI dashboard on `harness start`**, not the CLI. Make the browser the primary interface; relegate CLI to an opt‑in `--cli` flag. This matches every competitor’s first‑screen layout (chat window, not a terminal).

2. **Ship a single‑file `.exe` installer that bundles Python + dependencies**, handles DPAPI enrollment, and lands the user on the dashboard within 30 seconds. Current “git clone + pip install” is a blocker that rival products (LM Studio, Ollama desktop) solved years ago.

3. **Replace the YAML settings panel with a GUI modal** (model selection, API key input, engine fallback order, temperature). Hide every YAML file behind “Advanced Settings”. Non‑technical users will never touch YAML.

### 4. Cut or Hide
**Harness Coordination (coord) – all 13 subcommands.** A chat‑tier user does not want a multi‑agent worktree pipeline. They want a single text box and a send button. Move `coord` to a hidden `--advanced` namespace or deprecate it entirely.

### 5. One Risk Most Likely to Derail Trajectory
**Continuing to build CLI depth (more verbs, flags, YAML knobs) under the illusion that “operator profiles” can paper over the absence of a GUI.** Every wave spent on CLI features directly widens the competitive chasm with ChatGPT Desktop / LM Studio / Open‑WebUI, which already deliver a zero‑config chat experience.

### 6. Single-Sentence Recommendation
Pivot now: freeze all CLI‑only features, build a one‑click installer + default web UI in W11–W13, and treat the current CLI as a power‑user add‑on; otherwise the project will never serve its intended non‑technical audience.

---

## R6-user-research-proxy  (mimo/mimo-v2.5-pro)

**1. Headline verdict**
YES-IF — but only if the next 1-2 waves flip the product inside-out from infrastructure-first to interaction-first; as currently oriented, 0 of the 5 personas ever reach their first answer.

**2. Wave-count estimate**
5 waves p50 (W11-W15), 3-8 p90. The lower bound assumes W11 ships a working "ask" verb + standalone installer and W12-W15 polish trust, hiding, and cost visibility. The upper bound assumes continued infrastructure-first prioritization that keeps leaking UX debt forward.

**3. The 3 most load-bearing W11 decisions**

| # | Decision | Why it's load-bearing |
|---|----------|----------------------|
| 1 | **Ship `harness ask "<question>"` as the primary verb.** One command. Auto-selects healthy engine. Returns the answer in terminal. Zero config, zero preflight gate. This is the missing faucet — right now the harness is all plumbing, no spout. Every persona below bounces because there's nothing to *do* after install. | Without this, the product has no user-facing purpose for a chat-tier user. Full stop. |
| 2 | **Eliminate the git_clean preflight blocker via a first-run path that never triggers it.** Either `harness start wizard` creates a clean working tree silently, or preflight downgrades git_clean from FAIL to WARN on a fresh clone with no user commits. The W10 panel's 8/10 "WITH GUARDRAILS" and 2/10 "NO" both cite this as the single concrete failure point. | Every persona hits this wall on day one. It's the front door with a deadbolt. |
| 3 | **Ship a one-file installer (`.bat` or embedded Python zip) that replaces `git clone && pip install`.** Doesn't need to be .msi yet — even a `harness-setup.bat` that downloads, extracts, and runs `pip install -e .` silently is enough. | The parent, teacher, and small-business owner never reach preflight because they're already gone at the install step. |

**4. The one thing to CUT or HIDE**
**Coord V2 multi-agent worktree pipeline** — bury every coord subcommand behind `harness --advanced` or a `harness advanced` namespace. The 13 coord verbs, worktree isolation, heartbeat streams, and Planner→Worker→Coordinator→Integrator concepts are invisible complexity to all five personas. Even the hobbyist coder won't use them until they're deep into the tool. Showing them in default `--help` actively signals "this tool is not for you."

**5. The one risk most likely to derail the trajectory**
**The team continues to iterate on infrastructure (observer recovery, mutation pattern expansion, async flips, cost widgets) while the interaction surface remains absent.** Every wave in the snapshot is dispatch-layer, detection-layer, or coordination-layer work. There is zero user-facing interaction model — no "ask," no "chat," no "do this task." If W11 ships observer self-recovery and L5 escalation contracts instead of the "ask" verb and installer, the trajectory doesn't stall — it actively diverges from the chat-tier user, who will never know the harness exists.

**6. Single-sentence recommendation**
Pivot W11 hard: build the faucet (`harness ask`), fix the front door (first-run / installer), and hide the plumbing — because today a chat-tier user downloads the repo, fails preflight, and uninstalls before they ever type a question.

---

**Persona journey annex** (condensed):

| Persona | Drop-off point | Closest to fit? |
|---------|---------------|-----------------|
| Parent trying Kimi | Never passes `git clone` | No |
| High-school teacher | Fails preflight, doesn't know what "engine" means | No |
| Small-business owner | Sees YAML config, closes terminal | No |
| Journalist | Wants "paste article → summary"; no such path exists | No |
| Hobbyist coder | Might survive install + preflight; asks "now what?" and finds only infra verbs | **Closest, but still a 3/10** — they'll use it if `harness ask` exists and the CLI feels like a smart API wrapper, not a DevOps toolkit |

The hobbyist coder is the natural beachhead. But even they need a reason to stay past minute five, and that reason is currently missing.

---

## R7-cost-realist  (deepseek/deepseek-v4-flash)

**1. Headline verdict**  
YES‑IF the operator prioritises a zero‑cost distribution model (PyInstaller + GitHub releases) and keeps API spend below ~$50/month by relying on free‑tier Kimi/MiMo and occasional DeepSeek pay‑per‑token.

**2. Wave‑count estimate**  
6 waves p50, 4–9 p90. The distribution layer alone (installer, auto‑update, first‑run wizard) requires 3–4 focused waves; the remaining 2–5 waves are needed to sand off the sharp edges (pre‑flight git_clean fix, default dashboard, hiding advanced verbs).

**3. Three load‑bearing decisions for W11**  

- **Choose the distribution medium and commit to it** – either a true standalone .exe (via PyInstaller + optional code‑signing) or a simplified `pip install harness` + launcher script. Code‑signing ($300–500/yr) is avoidable; skip it and accept the “unknown publisher” warning – chat‑tier users will tolerate it if the first‑run wizard works.  
- **Kill the git_clean blocker in preflight** – replace it with a warning instead of a hard FAIL, or automatically stash/ignore untracked files. This single change eliminates the #1 reason all NO reviewers voted against ship.  
- **Build a single‑command `harness start` wizard that does everything** – creates the config, sets up DPAPI (via the existing env‑wizard), and runs preflight with the reduced gate. No YAML editing, no manual steps.

**4. One thing to CUT or HIDE**  
The entire **coord V2 multi‑agent pipeline** (13 subcommands: plan/run/work/retry/integrate/replan etc.). A chat‑tier user will never touch it. Hide it behind `--advanced` or remove it from the default help. Saves maintenance overhead and reduces confusion.

**5. The one risk most likely to derail**  
**API cost creep** during build and testing. Currently the operator burns free‑tier credits from Kimi/MiMo and occasional DeepSeek tokens. As they iterate on the installer and first‑run flow, they may need many LLM calls per wave (e.g., debugging bundling, auto‑update logic). If a single wave exceeds the free tier’s daily limit, they either stall or start paying. A worst‑case wave could cost $10–20 in DeepSeek/Claude API fees. Over 6 waves that’s $60–120 – affordable, but a sudden spike (e.g., needing to test on Windows without a dev machine) could push it to $200+ and trigger abandonment.

**6. Single‑sentence recommendation**  
Go, but pivot to a no‑frills, unsigned installer delivered via GitHub Releases, and enforce a strict API budget of $50/month by relying primarily on free‑tier Kimi/MiMo for the build process.

---

## R8-kill-project-skeptic  (mimo/mimo-v2.5-pro)

**1. Headline verdict**
NO — a ChatGPT-tier user will never tolerate a Git/CLI/Python stack when $20/month buys a polished product today; the harness has a fundamental abstraction mismatch with its target user that no wave count fixes.

**2. Wave-count estimate**
To reach genuine 7/10 for ChatGPT-tier users: **8 waves (p50), 6–14 (p90)**. That's W11–W18 minimum, because you still need: standalone installer, single-command first-run, dashboard-as-default, observer stability, cost surface, and hiding all the coordination/mutation plumbing behind a beginner mode. At current wave velocity that's **8–14 more weeks of operator-driven iteration** — with a non-technical operator who *cannot debug the inevitable regressions* each wave introduces.

**3. Three load-bearing decisions for W11**

- **Kill the Git-dependent install path entirely.** Ship a single self-extracting .exe (PyInstaller + embedded Python + embedded venv). If W11 doesn't land this, the first-run experience remains broken and the project cannot graduate from the pilot audience. This is not optional.
- **Default to dashboard mode; make CLI the advanced flag.** The operator's mental model is "type, get answer." Every `harness verb --flag` is a friction point. W11 must ship a localhost browser interface where the user types a prompt and sees responses, with all dispatch/audit/canary running invisibly behind it.
- **Implement a 3-click onboarding flow inside that dashboard** — engine key entry, health check, first prompt. The env-wizard CLI is the right idea but the wrong medium. If the first experience is a terminal, you've already lost.

**4. CUT or HIDE**
**Coord V2 (the entire multi-agent worktree system).** A ChatGPT-tier user will never invoke `harness coord plan/run/work/retry/integrate/replan`. This is a power-user orchestration layer that currently occupies a huge surface area in tests and code for zero end-user value. Park it behind an `--advanced` gate or a separate package. It's eating engineering attention disproportionate to its audience.

**5. The one risk**
**The abstraction mismatch is fatal.** The harness requires Git, Python, pip, YAML editing, Task Scheduler, and CLI fluency. The target user's self-declared mental model is "Claude Desktop." Every wave that optimizes CLI UX for a non-Python user is polishing a surface that the target audience doesn't want to touch. The risk isn't technical — it's that the project converges on a *very good tool for the operator themselves* rather than a product for ChatGPT-tier users, and no one notices the difference because the operator is the only tester.

**6. Alternatives comparison and recommendation**

| Path | Time-to-chat-tier | TCO (12 mo) | Multi-engine | Audit/canary | First-run friction |
|---|---|---|---|---|---|
| **W11→W18 harness** | 8–14 weeks | Operator time (unbounded) + hosting | ✅ | ✅ | Still broken until W12+ |
| **(a) OpenWebUI fork + plugin** | 3–5 weeks | ~$0 (open source) + 40h dev | ✅ (plugin) | ❌ (build later) | Browser; near-zero |
| **(b) LangFlow fork** | 4–6 weeks | ~$0 + 50h dev | ✅ (native) | Partial (flow-based) | Browser; low |
| **(c) ChatGPT Plus** | 0 weeks | $240/yr | ❌ (single engine) | ❌ | Zero |

The unique value that survives comparison is **the audit/canary/proxy-pool safety layer**. That's genuinely unusual and not available in alternatives (a)–(c). But that value doesn't require the current harness architecture — it could be a Python package imported into OpenWebUI or a standalone proxy service.

**ABANDON the harness-as-product.** Extract the dispatch + circuit-breaker + audit + canary core into a standalone `llm-proxy` service (pip-installable, runs as a local HTTP proxy on port 8888). Wire it into **OpenWebUI** (fork) as the single backend URL. That path reaches 7/10 for ChatGPT-tier users in **3 waves**, not 8, and the operator only needs to install two things once.

---
