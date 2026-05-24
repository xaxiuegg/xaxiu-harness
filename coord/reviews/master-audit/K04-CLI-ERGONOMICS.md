<!-- name=K04-CLI-ERGONOMICS latency_ms=85454 error='' -->

## Score

1. **Correctness** — 3. Functional, but the flat 38-verb surface with fractured namespaces (`engines-heal` vs `engines`, `spec-init` with no `spec` group) breaches the ergonomic consistency implied by operator-readiness specs.
2. **Robustness** — 2. No visible typo tolerance or collision guard; a non-technical operator mistyping `engine` instead of `engines` gets no corrective nudge.
3. **Operator-usability** — 1. `--help` is an ungrouped wall; three random samples: `coord` hints at subcommands in its description (2/5), `engines` hides `heal`/`cooldowns` as hyphenated top-level commands (1/5), and `observer` lists 12 subcommands with zero top-level hint (1/5).
4. **Test discipline** — 1. Thousands of tests exist, yet none enforce CLI taxonomy, help formatting, or verb-naming conventions.
5. **Risk** — 4. High probability of operator confusion between `engines-heal` and `engines heal`, missing `--fix` flags, and inability to browse commands without the runbook open.

6. **Top blocker** — Collapse hyphenated top-level verbs into nested subcommands (`harness engines heal`, `harness spec init`, `harness env wizard`) and add logical groups to `--help`.
7. **Verdict** — SHIP-WITH-FIXES: the core works, but the flat CLI namespace is a daily tax on the non-technical operator that directly undermines Track B goals.
