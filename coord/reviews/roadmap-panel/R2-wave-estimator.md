<!-- persona=R2-wave-estimator status=OK (22202ms) -->

# R2-wave-estimator

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
