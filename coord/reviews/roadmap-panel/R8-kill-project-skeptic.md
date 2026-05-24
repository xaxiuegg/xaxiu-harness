<!-- persona=R8-kill-project-skeptic status=OK (34145ms) -->

# R8-kill-project-skeptic

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
