<!-- name=K5-honest-readiness latency_ms=120026 error='' -->

## Rubric

1. **Install** — 1. Preflight exits 4 with git_clean and observer timeout; “commit or stash” is not something a non-technical user does.  
2. **Daily run** — 2. `harness daily` exists, but the routine is blocked by preflight failures and an unregistered dev loop.  
3. **Observe** — 3. Dashboard and morning-brief are operator-friendly, yet the observer probe timing out means the picture cannot be trusted without help.  
4. **Recover** — 2. Engine-specific healing exists, but bootstrap failures (git state, loop registration, observer hang) lack one-button remediation.  

5. **Hand to a non-technical operator today?** NO. The surface area is impressive, but the very first gate—`harness preflight`—hard-fails with a git hygiene error and an observer timeout. A non-technical friend cannot stash commits or debug why the observer probe hangs. Until the harness can bootstrap itself from a fresh clone to a green preflight without Python or git knowledge, it remains a dev tool, not an operator appliance.

6. **Top 3 blockers**
   - `harness install --autonomous` that auto-resolves git_clean (auto-stash or ignore), registers the dev loop, and seeds the observer so preflight exits 0 on first run.
   - `harness daily --repair` that internally fixes preflight/loop/observer warnings before doing work, collapsing the morning routine to one command.
   - A bulletproof `dashboard-serve` that falls back to a static, engine-less status page when the observer is down, guaranteeing the operator always has a readable health view.
