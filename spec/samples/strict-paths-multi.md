# SPEC-ID: strict-paths-multi — multi-file strict-path enforcement

## Goal

Create a small two-file "release notes pair" for the Wave 5 closeout:

1. A human-readable markdown release notes document.
2. A machine-readable JSON index of the same content (title, date, ship-list).

Both files MUST land at the exact paths declared under Strict Paths so an
operator's release-tooling can rely on them existing.

## Strict Paths

- coord/operator/wave5-closeout-notes.md
- coord/operator/wave5-closeout-notes.json

## Acceptance

1. Both files exist at the declared paths in the worktree post-dispatch.
2. The markdown file mentions at least 3 of the 7 Wave 5 ships:
   W5-V (Kimi wiring fix), W5-W (max_tokens unbounded), W5-Y/DD (L5
   escalation), W5-Z (install-scheduler bounds), W5-AA (Kimi-API
   planner), W5-BB (strict paths), Phase 3 Path β milestone.
3. The JSON file is valid JSON and contains a `title` string and a
   `ships` array.
4. No tests required — documentation deliverable.

## Why this spec exists

W5-CC shipped a single-path strict-paths sample.  This spec exercises
the cross-path enforcement: when the planner allocates a single worker
step covering both target files, the worker packet must list BOTH
strict paths in the STRICT PATHS callout, and the post-validation
must verify BOTH files exist.

Together with strict-paths-demo.md, these samples cover:
- Single-path enforcement (demo.md)
- Multi-path enforcement (this spec)

Future strict-path edge cases (cross-step splitting, glob patterns)
can graduate to additional sample specs.
