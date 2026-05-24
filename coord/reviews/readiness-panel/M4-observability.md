<!-- name=M4-observability latency_ms=36179 error='' -->

## Rubric

**1. Install — 3/5**
`doctor` + `preflight` surface issues with clear "Run to fix:" hints — excellent. But preflight *currently fails* (exit code 4) and resolving the `git_clean` blocker requires git knowledge the operator lacks. No one-click `preflight --fix` path exists.

**2. Daily run — 4/5**
`morning-brief`, `daily`, and `coord status` form a clear triad. Observer cadence runs autonomously. Minor deduction: the brief output wasn't shown — can't confirm it surfaces everything the operator needs (dispatch outcomes, engine health, blockers).

**3. Observe — 2/5**
This is the weakest surface. The **dashboard at 7878** is the primary visibility layer for a non-technical operator, but its actual rendered content is unknown — I can't verify it shows dispatch status, engine health, or escalation flags. STATUS.csv is canonical but is a flat file the operator must open; 310 rows without filtering/facets is opaque. Observer flags exist but the probe is currently *timed out*, so this surface is dark. The gap between "I can run `coord status`" and "I can watch a run without opening `runs/`" is large.

**4. Recover — 3/5**
`engines-heal`, `engines-cooldowns`, and `preflight` remediation hints are good. The MiMo filter issue shows the team *documents* failures in STATUS.csv with root cause — exemplary. But stderr tracebacks from dispatch failures have no operator-friendly translation; when something breaks mid-run, the operator must still dig into files or paste output to someone technical.

**5. Hand to a non-technical operator today? — WITH GUARDRAILS**
The CLI surface is well-designed for the profile: verb-noun commands, `doctor`/`preflight` gates, remediation hints. But three gaps block autonomous operation: preflight is currently failing with no self-service fix for the git blocker, the observer watchdog is down (so the operator's monitoring safety net is absent), and the dashboard's actual adequacy is unverified. With a technical person on call for escalations and a same-day fix for the preflight/git issue, it's usable today. Without that, the operator will get stuck within the first hour.

**6. Top 3 blockers**

1. **Dashboard rendering audit** — ship screenshots or a spec of what the 7878 dashboard actually shows; if dispatch status, engine health, and escalation flags aren't rendered, the non-technical operator has no real-time observability. Fixing this could move overall score from ~3 to ~4.
2. **Preflight self-repair for `git_clean`** — add a `harness preflight --autofix` that runs `git stash` automatically. Currently this is a hard blocker the operator can't resolve alone.
3. **Observer probe timeout resolution** — the observer is the watchdog on dev-manager authority; with it dark, there's no autonomous safety net. Either auto-restart it in the install path or surface the failure as a dashboard banner with a one-click remediation command.
