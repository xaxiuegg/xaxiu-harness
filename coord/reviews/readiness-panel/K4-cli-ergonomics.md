<!-- name=K4-cli-ergonomics latency_ms=52578 error='' -->

## Rubric

1. **Install** — 2. `harness install` and `doctor` are helpful, but `preflight` fails on `pytest_cache` (expects the operator to run/fix Python tests) and `dead_engines` remediation requires inspecting a `.jsonl` log—both violate the no-code constraint.
2. **Daily run** — 3. `morning-brief` is a well-named primitive, yet it is buried among 22 verbs with no single obvious “start my day” sequence or alias surfaced in the CLI.
3. **Observe** — 3. `dashboard-serve`, `STATUS.csv`, and `observer` provide visibility, but there is no top-level `status`/`today` command; the operator must manually synthesize `coord`, `engines`, and `observer` output.
4. **Recover** — 2. `preflight` and `doctor` surface hints, but fixes for engine death and pytest cache require code changes or structured-log forensics, leaving a non-technical operator stuck.

## Operator readiness

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. They can run `harness install`, read `STATUS.csv`, and open the dashboard, but any `preflight` failure—especially `pytest_cache` or dead engines—requires Python debugging or JSONL inspection they cannot perform. A technical teammate must greenlight the first run and handle engine rotation.

## Top 3 blockers

6. **Top 3 blockers**
   - **`harness today` (or `status`) verb:** a single human-readable summary of loop health, last dispatch, and observer alerts, eliminating the need to manually join `coord`/`observer`/`engines` output.
   - **`harness preflight --fix` / `harness quarantine`:** automated remediation for dead engines and stale pytest cache without asking the operator to touch source code or `.jsonl` logs.
   - **`harness daily` alias:** one obvious entry point that composes `morning-brief`, loop liveness, and observer status; 22 verbs create decision paralysis for non-technical users.
