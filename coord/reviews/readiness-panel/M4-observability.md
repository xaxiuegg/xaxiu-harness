<!-- name=M4-observability latency_ms=24042 error='' -->

## Rubric

1. **Install** — 4/5. `doctor` and `preflight` are clean CLI commands with clear OK/FAIL output. But `git_clean` warning with exit code 1 requires knowing what "3 untracked files" means and whether it's safe to ignore — a non-technical operator won't know.

2. **Daily run** — 4/5. `morning-brief` + `harness loop` + dashboard-serve is a clear three-command sequence. The --help is legible. Missing: a single `harness start-my-day` wrapper that chains them, or a morning checklist in a non-technical-friendly format.

3. **Observe** — 3/5. This is the crux. Dashboard at 7878 + STATUS.csv + observer flags + morning-brief give surfaces — but STATUS.csv's "Notes" column is wall-of-text technical prose (commit SHAs, module names, KB counts). The observer's authority audit output format is unknown from the snapshot. The operator *can* see status, but interpreting it requires reading dense technical notes or clicking through a dashboard whose UX isn't described. The gap: no evidence of a human-readable "what happened overnight" narrative that the morning-brief actually produces in plain language.

4. **Recover** — 3/5. `engines-heal` exists, `engines-cooldowns` exists, `doctor` diagnoses env issues. But the W9 rows expose real gaps: proxy fail-open/fail-closed behavior is undocumented, silent exceptions aren't audited, and a non-technical operator facing a traceback has no `harness fix-it` or structured remediation flow. Recovery paths exist for engines; they're thin for everything else.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surface is rich and the `doctor`/`preflight` commands gate startup. But observability relies on STATUS.csv whose Notes column reads like engineer commit logs, not operator guidance. The morning-brief may or may not produce plain-language output — the snapshot doesn't confirm it. An operator can *install and start the loop*, but would struggle to interpret what's happening or recover from non-engine failures without hand-holding.

6. **Top 3 blockers**
   - **`harness today` or morning-brief that outputs a plain-language "here's what happened, here's what needs attention"** — right now STATUS.csv Notes are developer prose, not operator guidance.
   - **`harness explain <ID>` that translates a STATUS.csv row into "what is this, is it blocking me, what do I do"** — closing the interpretability gap for the 296-row tracker.
   - **`harness fix-it` or structured remediation for common non-engine failures** (git dirty, observer flag raised, loop stalled) — right now only engine recovery has CLI verbs.
