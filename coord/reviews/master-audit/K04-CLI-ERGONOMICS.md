<!-- name=K04-CLI-ERGONOMICS latency_ms=79372 error='' -->

## Score

1. **Correctness** — 2/5. Inconsistent hyphenation (`spec-init` vs `init`, `engines-heal` vs `engines heal`) fractures the command taxonomy.
2. **Robustness** — 2/5. `preflight` and `today` silently hard-timeout after 30s with no progress indicator or partial output.
3. **Operator-usability** — 2/5. Flat, alphabetical dump of 30+ verbs offers no grouping; non-technical operators cannot map intent to command.
4. **Test discipline** — 2/5. No visible CLI integration tests for the W8 operator-facing verbs that demonstrably hang in production.
5. **Risk** — 4/5. High probability of operator mis-invocation, abandoned readiness checks, and escalation fatigue from hung commands.

**Discoverability (3 verbs)**
- `coord` — 4/5. Subcommands (`plan, run, integrate, status`) are discoverable directly in the top-level description.
- `engines` — 2/5. `heal` is a hidden subcommand shadowed by top-level `engines-heal`/`engines-cooldowns` aliases.
- `observer` — 2/5. One-line help teases "authority audit" but buries 12 subcommands behind a second `--help` layer.

**Top blocker** — Unify all engine operations under `harness engines {heal|cooldowns|reliability}` and remove the hyphenated top-level aliases so intent maps to a single namespace.

**Verdict** — SHIP-WITH-FIXES. W8 capabilities are operationally necessary, but the CLI surface is actively hostile to the non-technical operator it was built for.
