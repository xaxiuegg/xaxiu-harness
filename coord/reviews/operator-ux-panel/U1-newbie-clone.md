<!-- persona=U1-newbie-clone status=OK (26334ms) -->

# U1-newbie-clone

**Top 3 changes (ranked):**
1. **`harness start` single-path wizard.** A single command that runs `doctor`, `preflight --fix --allow-stash`, generates a `.env` from a template (interactive key entry), starts the observer, and ends by opening `dashboard-serve`. Eliminates all command-choice paralysis and diagnostic interpretation.
2. **Profile-aware defaults that hide failure complexity.** When `--profile non_technical` is active (or detected), `preflight` should never exit non-zero on `git_clean`; instead, auto-stash with a loud warning and list files in plain language. Errors must show remediation as step-by-step commands, not just error codes.
3. **"Show me it works" trust demo.** After setup, the wizard runs a safe `harness dispatch ping-engine --dry-run` and prints a styled "✅ Your harness can talk to Engine [X]" with a timestamp and engine name. Proof, not just configuration.

**Wave 11 candidate:** `W11-FIRST-RUN-HEALTH-GATE`
*Acceptance criteria:* After `harness start` completes, the operator sees a single green status bar (e.g., "All 3 engines ready. Observer running. Queue empty. Next check: 09:00."). If any component is unhealthy, the gate shows a clear "Fix this now" link/step. No ambiguity about whether the system is operational.

**Kill or hide:** The top-level `engines-*` verb family (`engines-cooldowns`, `engines-heal`, `engines-reliability`). For a non-technical operator, engine management is a "call engineering" event. These should be moved under `harness engines --advanced` or accessed only via the dashboard's "Engine Health" panel, which can then show a "Copy this status for support" button.

**Minimum viable first-run path (≤5 steps):**
1. Double-click `harness-start.bat` (or run `harness start`).
2. Terminal prompts: "Enter your DeepSeek API key: _______"
3. Terminal prompts: "Enter your Kimi API key: _______" (or "skip").
4. Command auto-runs, shows progress ("Checking git... OK, Stashing files... OK, Starting observer... OK").
5. Browser opens to `localhost:8080` showing dashboard with a green "System ready" banner and a sample audit log entry.

**Trust seam:** **The morning email brief.** A non-technical operator trusts a daily email they didn't have to generate. `harness install` should offer to set up a 08:00 AM Windows Scheduled Task that runs `harness today --email operator@company.com`. The email is plain text: "Here's what happened overnight and your next actions." Seeing a reliable, unprompted summary in their inbox builds trust that the system is working autonomously.
