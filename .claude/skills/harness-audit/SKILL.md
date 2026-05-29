---
name: harness-audit
description: Cross-vendor fact-check / ship-audit of a claim or change via the harness. Runs `python -m harness ask --audit` (producer + a DIFFERENT-vendor auditor) and reports the verdict. Use for a quick cross-engine second opinion before shipping.
---

Run a cross-vendor audit through the harness and report the result.

1. From the repo root, run:

       python -m harness ask "$ARGUMENTS" --audit

   `$ARGUMENTS` = the claim, question, or summary-of-change to verify. If it is
   empty, ask the user what to audit before running.

2. Read the printed `-> review at <PATH>` directory's `summary.json` and report
   the `verdict` (PASS / PARTIAL / FAIL / UNKNOWN), plus the auditor's
   `corrections` and `missed` fields. Note which engines produced + audited.

3. Do NOT substitute your own single-vendor judgment for the cross-vendor
   result — the entire point is a *different* vendor's model checking the work
   (Claude shares blind spots with the in-session driver).

This is the operator-invocable twin of the `cross-vendor-panel` subagent: both
route verification through the harness so it never silently falls back to a
single Claude session. See CLAUDE.md "Native CC features vs. the harness".
Invoked as `/harness-audit` — named to dodge the unanchored `audit/` .gitignore
rule that excludes any directory literally named `audit`.
