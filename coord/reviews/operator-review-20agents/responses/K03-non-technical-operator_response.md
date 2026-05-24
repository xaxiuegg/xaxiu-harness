### Verdict
NEEDS-WORK

### Confidence
0.35

### Top-3 concrete recommendations
1. **Replace every Unicode glyph in CLI output with ASCII-safe characters on Windows** so `harness --help`, `harness preflight --fix`, and `harness agent init` stop crashing with `charmap` errors before I can even read the instructions. Grounded in evidence 04 (preflight arrow crash), 06 (help alpha crash), and 15 (agent init checkmark crash). Effort: S.

2. **Wire the dashboard to the live Wave 11 endpoints** — cost widget, L5 banner, preflight latency, and recent commits all return "Not Found" or are entirely absent, leaving the landing page three days stale and useless for situational awareness. Grounded in evidence 00 (missing widgets, stale loop) and 12–14 (API `{"detail":"Not Found"}`). Effort: M.

3. **Harden the preflight remediation path** so that when checks fail the operator sees the plain-language fix card (e.g., "Run to fix: harness preflight --fix --dry-run") instead of a traceback swallowing the advice. Grounded in evidence 04 (L5 banner prints, then immediate Unicode crash). Effort: S.

### Operator vote
WAIT-FOR-WAVE-12

### Single quote from evidence
"UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 5: character maps to <undefined>"