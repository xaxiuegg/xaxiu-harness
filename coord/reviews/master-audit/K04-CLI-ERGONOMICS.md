<!-- name=K04-CLI-ERGONOMICS latency_ms=90785 error='' -->

## Score

1. **Correctness — 2/5** Taxonomy is broken: ~38 top-level verbs (lens spec expected 22), `loop`/`loops` collide, `engines-heal` mirrors `engines heal`, and `doctor`/`preflight` overlap.
2. **Robustness — 2/5** No visible typo correction or subcommand-Levenshtein guard; plausible mis-typings like `harness engine cooldowns` fail opaquely.
3. **Operator-usability — 2/5** Non-technical operator faces an undifferentiated flat list; `spec-init`, `spec-register`, `spec-verify` are separate incantations instead of a `spec` family, and `--help` lacks workflow grouping.
4. **Test discipline — 1/5** 1,576 tests pass, yet no CLI-ergonomics regression coverage is evidenced (no `--help` snapshot tests, no subcommand-discovery assertions).
5. **Risk — 4/5** Every wave adds top-level verbs rather than nesting; operator-readiness foundation from W8 will be undermined by CLI sprawl.

**Three-verb discoverability spot-check:**
- `engines`: 1/5 — `heal`, `cooldowns`, `reliability` are hidden as hyphenated top-level aliases, not listed under `engines`.
- `observer`: 2/5 — 12 subcommands exist but top-level `--help` only gives an abstract tagline.
- `coord`: 4/5 — `plan`, `run`, `integrate`, `status` are explicitly advertised in the short help.

**Top blocker:** Reify a true noun/verb hierarchy (`harness engines heal`, `harness spec init`) and prune duplicate top-level aliases; group `--help` by operator workflow.

**Verdict:** SHIP-WITH-FIXES. W8 operator-readiness gains are real, but the flat CLI surface is a self-inflicted maze that will trap the non-technical operator.
