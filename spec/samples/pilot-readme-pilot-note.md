# PILOT-README-PILOT-NOTE: append a Path-2 pilot note to README.md

**Purpose**: Second Path-2 pilot spec to prove reproducibility across
different content + different file (not just CHANGELOG.md).

## Goal

Append a `## Path-2 Pilot Notes` section to the bottom of README.md
describing this session's pilot work in 3-6 bullet points.

## Acceptance

1. README.md contains a new section heading `## Path-2 Pilot Notes`
   appended at the end of the file (or immediately before any existing
   trailing footer).
2. The section has 3-6 short bullets covering at least:
   - First real-engine end-to-end pilot landed (run-id mentioned)
   - W5-J CRLF-tolerant FILE/REPLACE shipped
   - W5-M PID sentinel prevents worker race
   - One sentence on harness production-readiness status
3. Existing README content above the new section is unchanged.

## Why this spec exists

This is the *second* Path-2 pilot, run after the operator pointed out
that one-shot success doesn't prove "demonstrably ready".  This spec
deliberately uses a **different file** (README.md instead of
CHANGELOG.md) and **different edit shape** (append-at-end instead of
insert-before-section) so reproducibility includes content variety.

## Why README.md

- Docs-only (no code-path risk)
- Different file from the first pilot (CHANGELOG.md)
- Append-at-end pattern (different from before-section-insert)
- Easy operator audit (open README.md, read the note)
