<!-- persona=U8-pragmatic-roadmap status=OK (25590ms) -->

# U8-pragmatic-roadmap

**Top 3 changes (ranked):**
1.  **`harness day-start` (one command)**: Replace the 3-command morning sequence with a single verb that runs `preflight`, then `today`, then `observer status`, piping the output into a clear, green/yellow/red terminal report. This eliminates decision fatigue and gives a single, trustworthy daily ritual.
2.  **`preflight --operator` profile**: Make this the default for non-technical users. It auto-silences `[X] git_clean` (run `git stash` automatically), explains `[!]` warnings in plain language ("Your API key for DeepSeek is missing"), and presents remediation as a simple "Run this command" line. Integrates the runbook.
3.  **First-run `harness init` wizard**: After `harness install`, the wizard should generate a `GETTING_STARTED.md` with a personalized 3-step plan (based on `doctor` output), set the operator profile, and schedule the first `day-start`. No choice, no docs to read.

**W11 Candidate:**
`W11-DASHBOARD-TRUST-CARD`
Add a single, auto-refreshing panel to `dashboard-serve` and `morning-brief` called "System Trust." It shows: 1) Last successful dispatch (timestamp, engine, result), 2) Next scheduled loop, 3) Observer status (green/red). Acceptance: A non-technical operator can glance at the card and in 5 seconds know if the system is healthy and active.

**Feature to KILL:**
**Hide 80% of the CLI.** Move `adapter`, `budget`, `burst`, `coord`, `engines-cooldowns`, `engines-reliability`, `lock`, `orchestrator` behind `--advanced` in `--help` or into a separate `harness-admin` command. The daily operator surface should be ≤10 verbs: `day-start`, `status`, `today`, `queue`, `observer`, `dashboard`, `engines-heal`, `doctor`, `init`, `panic-dump`.

**Minimum Viable First-Run Path:**
1.  Run `harness install` (schedules Task Scheduler, runs wizard).
2.  Wizard prompts: "Paste your API keys" (with links to get them). Wizard sets them in DPAPI.
3.  Wizard says: "Your first run is scheduled for tomorrow at 9 AM. To run now, type: `harness day-start`".
4.  Operator runs `harness day-start`.
5.  Sees: "System Trust: [GREEN] All engines ready. Last dispatch: [none]. Next loop: tomorrow 9:00 AM. Suggested: Run `harness queue list` to see the first task."

**Trust Seam:**
**The `day-start` summary must include a "Last 24h Success" counter**—a simple "X of Y tasks completed successfully" with a link to a plain-text log. A number that stays green over days is the only signal a non-technical user will believe long-term.
