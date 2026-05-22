# PILOT-CHANGELOG-V06: extend CHANGELOG.md with v0.6 section

**Purpose**: Path-2 real-money DeepSeek pilot.  Lowest-blast-radius
end-to-end test of `coord plan -> run --watch -> integrate` against a
real engine.  Edits a single docs file only; no code paths affected.

## Goal

Add a new `## v0.6 — 2026-05-22 (W4-W5 hardening session)` section to
the top of CHANGELOG.md.  Keep the existing v0.5 section intact below
it.

## Acceptance

1. CHANGELOG.md contains a new section heading `## v0.6 — 2026-05-22`
   placed **before** the existing `## v0.5 — 2026-05-21` line.
2. The new section summarises this session's commits in 8-15 bullet
   points covering:
   - W4-A worker silent-noop guard
   - W4-B integrator silent-noop guard
   - W4-G multi-engine coverage campaign (20 dispatches)
   - W4-H CLI UX polish (engines list / lint-spec --spec / read_status default)
   - W4-J dispatcher MiMo silent-empty guard
   - W4-K token tracking from response.usage
   - W4-L end-to-end failure-path proof
   - W5-A swarm/mock direct routing
   - W5-B coord run --watch (auto-tick + auto-integrate)
   - W5-C engine reliability digest auto-published
   - W5-D budget by-run cost-per-run rollup
   - W5-F cross-engine source-laden verification
   - W5-G silence Unknown-engine warning for mock
   - W5-H coord integrate --no-merge
   - Path 3 telemetry in --watch
3. Bullet format follows v0.5 style: short backtick commit-style label
   then description.  Commit SHAs optional (we don't have them in the
   spec; engine may omit or use placeholders).
4. The existing v0.5 section is unchanged.

## Why this spec exists

This is the first **real-money** Path-2 pilot proving the harness end
to end with the production engine (DeepSeek v4-flash, W5-F empirical
3/3 reliability).  Docs-only edit = lowest possible blast radius.  If
it works, the harness is production-ready for unattended overnight.
If it fails, the W4-A/B/J guards catch it cleanly.

## Why CHANGELOG.md

- Markdown (simple to edit, no syntax to break)
- One file (no multi-worker dependency complexity)
- One section to add (one FILE/REPLACE block)
- Reversible (operator can `git revert` if output is bad)
- Auditable (operator can read the generated section to grade engine
  output quality)
