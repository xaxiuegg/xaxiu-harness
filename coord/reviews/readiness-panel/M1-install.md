<!-- name=M1-install latency_ms=22151 error='' -->

## Rubric
1. **Install**: 3/5 — `harness doctor` and `harness install` provide a clear path, but dead engines (preflight) require troubleshooting API keys and state files, likely needing help.
2. **Daily run**: 2/5 — Morning sequence (`preflight` → `loop`) is logical, but fixing `dead_engines` and `git_clean` failures isn't obvious without guidance; the non-technical operator can't parse the engine log.
3. **Observe**: 3/5 — `dashboard-serve`, `heartbeat`, and `STATUS.csv` give visibility, but correlating issues (e.g., from `observer` or `preflight`) into a simple "is it healthy?" view isn't automatic.
4. **Recover**: 2/5 — `preflight` lists fixes like rotating keys or stashing, but the operator lacks `doctor --fix` or one-command key rotation; dead engines and pytest failures require Python debugging.

**5. Hand to a non-technical operator today?** NO.
The operator can run commands, but the preflight failures (dead engines, dirty git, test failures) require inspecting JSONL logs, rotating API keys at the provider level, and debugging Python tests—tasks beyond their capability. Without a "fix" or "health-check" command that automatically resolves common issues (like `harness doctor --fix`), they will get stuck immediately.

**6. Top 3 blockers**
1. **`harness doctor --fix`** (missing): Should auto-stash git, rotate/quarantine dead engines, and skip failed tests.
2. **Key rotation CLI** (missing): `harness engines rotate <engine>` to refresh keys without env-var editing.
3. **Preflight ignore/override** (missing): `harness preflight --force` to bypass non-critical warnings for initial runs.
