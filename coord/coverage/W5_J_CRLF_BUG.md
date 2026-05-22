# W5-J: CRLF line-ending bug surfaced by Path 2 pilot

**Date**: 2026-05-22  
**Severity**: Ship-blocking — would have broken every overnight run that
edits Windows-checked-out files.

## Smoking gun

Path 2 pilot fired `coord run --watch --engine swarm/deepseek
--no-merge` against `spec/samples/pilot-changelog-v06.md`.

DeepSeek v4-pro generated a **PERFECTLY VALID** FILE/REPLACE block:

```
FILE: CHANGELOG.md
<<<<<<< SEARCH
## v0.5 — 2026-05-21 (autonomous session arc)
=======
## Session Commit Summary
- 22 sequential commits, 50+ STATUS rows, +395 tests …
…
## v0.5 — 2026-05-21 (autonomous session arc)
>>>>>>> REPLACE
```

Worker's `_apply_file_edits` checked `if search in content:` (byte-exact).
That check returned **False** even though the text *visually* matches.

Root cause: **line endings**.
- `CHANGELOG.md` has CRLF (`\r\n`) — checked via `xxd`.
- DeepSeek's response has LF (`\n`).
- `"## v0.5 — 2026-05-21 (autonomous session arc)\n"` is NOT a substring
  of `"## v0.5 — 2026-05-21 (autonomous session arc)\r\n"`.

W4-A correctly caught the resulting 0-files-modified as
`L3.dispatch.E_SILENT_NO_OP`.  No master pollution, no false success.
But the run *failed* when it should have *succeeded*.

## Why this didn't show up earlier

- Unit tests for `_apply_file_edits` used LF-only inputs.  No
  CRLF-vs-LF cross-coverage.
- The MockEngine in `tests/test_coord_smoke_e2e.py` writes LF content to
  LF files, also no cross-coverage.
- W4-L hello-world.md path created a *new* file (no existing CRLF to
  collide with).
- W5-A's swarm/mock e2e: same as W4-L — new file.
- Every previous "live" coord run created new files, never edited
  Windows-CRLF files.

The Path 2 pilot is the **first** time the harness ran against a
real, real-engine, edit-an-existing-CRLF-file workload.  It found the
gap immediately.

This is exactly the kind of finding the operator wanted Path 2 to
surface before unattended overnight.

## Fix (W5-J)

`src/harness/coord/worker.py::_apply_file_edits`:

1. **Read existing file as bytes** to detect line ending convention
   (avoid Python's universal-newlines decoding silently normalising
   `\r\n` to `\n`).
2. **Byte-exact match first** — preserves pre-W5-J behaviour for LF
   files (zero regression).
3. **Normalised retry** — if byte-exact misses, normalise both `search`
   and `content` to LF and retry.  If still misses, the SEARCH is
   genuinely absent (skip silently per existing semantics).
4. **Re-emit preserving line endings** — `_match_line_endings()` ensures
   we write the file back with its original convention so we don't
   leave the file with mixed line endings.
5. **New-file path** — switched from `write_text` (which on Windows
   converts `\n` → `\r\n` via default universal-newlines) to
   `write_bytes(replace.encode("utf-8"))` so engine output lands
   verbatim.

## Tests

7 new tests in `tests/test_w5_j_crlf_file_edit.py`:
- byte-exact match on LF file (regression guard)
- CRLF file + LF search matches in normalised space
- truly absent SEARCH still skipped
- multiline SEARCH with em-dash + CRLF
- new-file create writes LF (matches engine)
- empty-SEARCH append on LF
- empty-SEARCH append on CRLF (preserves CRLF)

All 38 worker tests pass (31 existing + 7 W5-J).

## Production impact

Before W5-J, overnight runs that edited any CRLF file would silently
no-op-fail.  W4-A would catch the silent-no-op (so no false success),
but the operator would wake up to "0 successful edits across overnight
run" with no explanation pointing at line endings.

After W5-J, FILE/REPLACE works equally on LF and CRLF files.  The
harness is now CRLF-tolerant — production code paths cross-platform-
safe.

## Path 2 pilot status

- v1 run (20260522T160259-6088): caught the CRLF bug; --no-merge
  prevented master pollution.
- v2 run (20260522T161502-e218): in flight, expected to land the
  CHANGELOG.md edit cleanly with the W5-J fix.

## Cost

Path 2 v1: DeepSeek v4-pro, 1921 input tokens + 3442 output tokens,
elapsed 67.76s.  At v4-pro pricing ~$0.0017.  Well under the $10/8h
cap.

## Operator-readable summary

Path 2 piloting **did its job**: surfaced a real ship-blocker before
unattended overnight.  W4-A caught the failure cleanly; --no-merge
prevented trunk pollution; the diagnostic (DeepSeek text + audit
file) was sufficient to root-cause and fix in 15 minutes.  This
single test was worth the entire Path 1/3/2 investment.
