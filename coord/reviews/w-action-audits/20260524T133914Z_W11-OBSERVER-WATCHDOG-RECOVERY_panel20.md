# 20-agent audit panel — W11-OBSERVER-WATCHDOG-RECOVERY (600b026d7758)

<!-- engine=20-panel task=W11-OBSERVER-WATCHDOG-RECOVERY sha=600b026d7758 mean_confidence=0.602 verdict=STOP -->

- **Verdict**: STOP
- Mean confidence: 0.602
- Personas passing (≥0.7): 7 / 15 (of 20 dispatched)
- Personas stopping (<0.7): 8
- Elapsed: 260.9s

## Per-persona verdicts

| Persona | Engine | Conf | Verdict | Lens finding |
|---|---|---|---|---|
| K01-correctness | kimi | 0.20 | STOP | The commit delivers stale-pulse detection, a platform-aware restart primitive, a |
| K02-test-quality | kimi | 0.35 | STOP | Tests verify stale-pulse logic with solid unit coverage, but restart and platfor |
| K03-api-surface (FAIL) | kimi | — | ? | engine returned empty/error: None |
| K04-error-handling | kimi | 0.35 | STOP | Cron scheduler audit fix correctly replaces silent swallow with _CrontabReadErro |
| K05-backwards-compat | kimi | 0.95 | PASS | The commit adds new watchdog verbs and cron_scheduler audit fixes without alteri |
| K06-documentation (FAIL) | kimi | — | ? | engine returned empty/error: None |
| K07-performance | kimi | 0.95 | PASS | Watchdog recovery adds cold-admin CLI verbs (watchdog-status, restart) that perf |
| K08-dependencies | kimi | 0.95 | PASS | Zero new pip packages introduced; the new watchdog module and cron_scheduler aud |
| K09-security | kimi | 0.90 | PASS | Commit remediates the prior K09 shell-injection finding by enforcing shlex.quote |
| K10-scope-creep | kimi | 0.25 | STOP | Commit bundles seven unrelated 20-agent panel audit markdown files (~318 lines)  |
| M01-architecture | mimo | 0.35 | STOP | watchdog.py cleanly layers atop observer/state + observer/scheduler via platform |
| M02-safety (FAIL) | mimo | — | ? | engine returned empty/error: None |
| M03-operator-ux (FAIL) | mimo | — | ? | engine returned empty/error: None |
| M04-cross-platform (FAIL) | mimo | — | ? | engine returned empty/error: None |
| M05-agent-ux | mimo | 0.88 | PASS | Watchdog exposes structured JSON via watchdog_status() + deterministic exit code |
| M06-audit-criteria | mimo | 0.40 | STOP | Criterion 1 (stale banner), 2 (restart verb with platform dispatch), and 4 (test |
| M07-spec-drift | mimo | 0.35 | STOP | Spec acceptance criterion #3 — L4 alarm fires on restart failure with L5 escalat |
| M08-forward-compat | mimo | 0.75 | PASS | New watchdog module locks in a keyset contract (is_stale, last_cycle_at, stale_s |
| M09-code-review | mimo | 0.78 | PASS | Watchdog module is well-structured (small focused functions, clean naming, consi |
| M10-regression-risk | mimo | 0.62 | PASS | K04 audit fix now refuses to mutate on crontab-read timeout, which is safer for  |

## Blocking concerns (personas with conf < 0.7)

- **M01-architecture** (0.35): The L4/L5 escalation contract is entirely missing: no state accumulator tracks consecutive restart failures, no observer flag or alarm primitive is invoked on failure, and no path to L5 exists — this is a load-bearing behavioral contract per the spec, not a cosmetic gap.
- **K02-test-quality** (0.35): The escalation chain acceptance criterion is completely untested; a hollow implementation of L4/L5 consecutive-failure logic would pass the 24/24 suite, making this a rubber-stamp test suite for the spec's riskiest requirement.
- **M06-audit-criteria** (0.40): One of four acceptance criteria (L4 alarm on restart failure with 3-consecutive-failures-to-L5 escalation chain, plus its tests) is completely unmet; the criterion is specific enough that any reasonable engineer would mark it a miss.
- **M07-spec-drift** (0.35): The L4/L5 escalation chain is a hard acceptance criterion with no code, no test, and no drift annotation — the STATUS.csv entry documents the audit fixes thoroughly but silently omits the alarm requirement, violating the contract that deviations must be documented.
- **K01-correctness** (0.20): Zero code or tests for the L4/L5 escalation chain: the spec mandates that a failed `harness observer restart` triggers an L4 alarm and escalates to L5 only on 3 consecutive failures, yet the commit only returns a (bool, msg) tuple from restart_observer with no wiring into the flag/escalation system,
- **K04-error-handling** (0.35): No evidence that the mandated L4/L5 escalation chain for restart failures is implemented or tested, constituting a hard acceptance-criteria miss.
- **M10-regression-risk** (0.62): The K04 crontab-read-timeout → refuse-to-mutate fix interacts adversarially with the new restart verb: a persistent read-timeout on the platform makes both observer-arm and observer-restart permanently fail with no escalation path, converting the original silent-corruption bug into a silent-unavaila
- **K10-scope-creep** (0.25): Seven unrelated panel audit reports and an unwired dashboard_banner() add pure maintenance burden and repository bloat without runtime value.
