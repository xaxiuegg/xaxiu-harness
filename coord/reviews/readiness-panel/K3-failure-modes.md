<!-- name=K3-failure-modes latency_ms=152806 error='' -->

## Rubric

**Failure modes (first month):**
1. **Git-dirty preflight FAIL** — Message is clear to a developer, but “Commit or stash” assumes git fluency; a non-technical operator will ping engineering. Recovery is not CLI-obvious.
2. **Observer probe timeout** — “Timed out” is clear, but the fix (`harness observer scheduler-status`) is opaque; if re-running preflight fails, operator pings engineering.
3. **Both-engines-failed (DeepSeek+MiMo cascade)** — The error is explicit, yet no CLI verb resolves a content-filter/key root cause; operator must ping engineering.
4. **Loop not registered** — Clear warning with exact fix (`harness loop start`); recovery is obvious without help.
5. **STATUS.csv blindness** — No error message, but 310 rows drown signal; operator lacks a filtered view and likely gives up reading it.

1. **Install** — 2. `env-wizard` eases API keys, but the git-dirty hard block + observer warnings make a ≤30-min green preflight unlikely without engineering help.
2. **Daily run** — 3. `daily` and `morning-brief` exist, yet sequencing isn’t self-evident; low-toil only after memorization or docs.
3. **Observe** — 3. Dashboard and `heartbeat` help, but observer timeout in preflight and noisy CSV erode confidence.
4. **Recover** — 2. `engines-heal`/`env-wizard` cover simple paths, yet git blocks and engine-cascade failures lack operator-grade recovery.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. Core commands exist, but preflight assumes git literacy, STATUS.csv is a firehose, and engine outages degrade to opaque errors. It is usable only if an engineer pre-clears git/loop state and remains on-call for engine-level failures.

6. **Top 3 blockers:**
- **`harness morning` unified verb**: Sequences daily/brief/preflight and narrates blockers in plain English.
- **`harness status today` filter**: Hides 300+ shipped rows to surface only active blockers.
- **`--operator-safe` preflight flag**: Auto-stashes or bypasses git dirty state so non-coders aren’t hard-blocked.
