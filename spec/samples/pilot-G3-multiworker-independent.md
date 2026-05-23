# PILOT-G3: multi-worker plan (2 independent workers, no dependencies)

**Purpose**: Phase B comprehensive — exercise multi-worker plan with
parallel-eligible workers writing to disjoint files.

## Goal

Two independent workers, each editing a different docs file:

- **Worker A**: appends a `## Pilot G3 Notes` section to
  `coord/coverage/W5_F_BUDGET_DIAGNOSIS.md` with 2-3 bullets about
  the verification campaign.
- **Worker B**: appends a `## Pilot G3 Notes` section to
  `coord/coverage/W5_J_CRLF_BUG.md` with 2-3 bullets about the CRLF
  diagnosis.

No `depends_on` between A and B; they can run in any order.

## Acceptance

1. Both files contain a new `## Pilot G3 Notes` section appended at end.
2. Both sections have 2-3 bullet points each.
3. Existing content of both files is unchanged.
4. Two separate worker checkpoints exist:
   - `runs/<rid>/checkpoints/worker-1.json` state=completed,
     files_modified=['coord/coverage/W5_F_BUDGET_DIAGNOSIS.md']
   - `runs/<rid>/checkpoints/worker-2.json` state=completed,
     files_modified=['coord/coverage/W5_J_CRLF_BUG.md']

## Why this spec exists

Multi-worker plans are the harness's main parallelism point.  G3
proves the coordinator spawns BOTH workers (W5-M PID sentinel
isolation), each succeeds independently, and integrator merges both
or reports both via --no-merge.
