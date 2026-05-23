# PILOT-G1: add module-level note to scripts/verify_source_laden_3engines.py

**Purpose**: Comprehensive Phase B — pilot a *real Python source* edit
to prove the harness works for code (not just docs).

## Goal

Insert a new comment block at the bottom of
`scripts/verify_source_laden_3engines.py` documenting the script's
relationship to the W5-3ENGINE matrix work.

## Acceptance

1. `scripts/verify_source_laden_3engines.py` contains a new comment
   block placed AFTER the existing `if __name__ == "__main__":` block.
2. The block contains 2-4 lines of `# ...` comments mentioning:
   - W5-F campaign / W5-3ENGINE matrix
   - Reproducibility of source-laden engine reliability findings
3. Existing code above (everything up to and including the
   `raise SystemExit(main())` line) is unchanged.
4. The script still passes `python -m py_compile`.

## Why this spec exists

Phase B comprehensive test: prove that real Python edits (not docs)
work end-to-end through the harness.  Comment-only edits are
behaviour-neutral so even if the engine mis-targets, no functional
change.
