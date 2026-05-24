<!-- persona=R4-ruthless-pm status=OK (23302ms) -->

# R4-ruthless-pm

1. **YES-IF**, but only if the operator accepts that ~40% of what the harness currently ships needs to be hidden behind `--advanced` or outright deferred — the current surface is a developer platform wearing an operator hat.

2. **4 waves p50, 3-7 p90.** W11: installer + single-verb entry point. W12: hide/defer engineering verbs, consolidate surface to ~5 commands. W13: error translation (tracebacks → plain English). W14: polish + dashboard default. The velocity has been good — the bottleneck is willingness to cut, not technical debt.

3. **The 3 load-bearing W11 decisions:**

   **a. Ship a Windows installer (`.exe` or `.bat` + bundled venv) that replaces git-clone entirely.** The git_clean preflight blocker is a death sentence for a chat-tier user. No installer = no path to 7/10, full stop. Even a self-extracting zip with a double-click `install.bat` that does `python -m venv`, `pip install .`, and `harness env-wizard` would close this gap.

   **b. Define `harness ask "..."` as THE default surface** — a single verb that routes to the best available engine, runs a soft preflight silently, and returns a plain-text answer. Today a chat-tier user has to understand engines, preflight, profiles, and dispatch. They shouldn't need to know any of that exists. `harness ask` should be the *only* thing documented on the README's first page.

   **c. Consolidate to 5 operator-facing verbs: `ask`, `daily`, `today`, `status`, `help`.** Everything else — `engines-heal`, `preflight`, `env-wizard`, `profile set`, `status list --recent` — gets folded into `daily`'s morning routine or hidden behind `--advanced`. The current 12+ verb surface is a tax on working memory that a chat-tier user will never pay.

4. **CUT: `harness engines-heal` as a standalone verb.** A chat-tier user will never diagnose engine health manually. Fold its logic into the circuit-breaker auto-fallback that already exists — engines *should* heal themselves. Exposing a manual heal verb signals to the user that the system is fragile and they're responsible for fixing it. That's the opposite of the trust model you need.

5. **Feature-count creep masquerading as progress.** W1–W10 added capabilities at a rate of ~1.5 new verbs or flags per wave. Each one feels small in isolation, but the cumulative surface is now a ~30-item mental model. If W11–W14 *add* the queued items (cost widget, morning email, L5 contract, dashboard default) without *removing* or hiding an equal number, the chat-tier user's experience degrades even as the feature list grows. The risk is that the operator treats the backlog as a queue to drain rather than a portfolio to cut.

6. **Go — but freeze all new features for one wave and hide half the existing ones.** The harness has the right engine underneath; it just needs a ruthlessly thin skin on top.
