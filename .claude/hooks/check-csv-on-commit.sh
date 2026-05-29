#!/usr/bin/env bash
# PostToolUse hook (xaxiu-harness scope) for Bash. Fires after a git commit;
# warns if the commit didn't touch coord/STATUS.csv.
#
# Mirrors the warehouse hook (D:/Projects/warehouse/.claude/hooks/check-csv-on-commit.sh).
# Per memory feedback_status_csv_canonical.md.
#
# Reads stdin (Claude Code hook input as JSON).
# Exit 0 = silent pass; exit 2 = emit feedback to Claude.

INPUT=$(cat 2>/dev/null || true)

# Scope guard — only act on xaxiu-harness turns.
if [[ "$PWD" != *"/xaxiu-harness"* ]] && ! echo "$INPUT" | grep -q "xaxiu-harness"; then
  exit 0
fi

# Only fire if the tool command included 'git commit'
if ! echo "$INPUT" | grep -q 'git commit'; then
  exit 0
fi

# Resolve the repo root from THIS script's location rather than hardcoding an
# absolute path.  The hook lives at <repo>/.claude/hooks/, so ../.. is the repo
# root.  (Hardcoding "D:/xaxiu-harness-standalone" broke on the repo migration
# and can't run on the Linux CI leg; `|| exit 0` keeps it fail-safe.)
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)" || exit 0
cd "$_HOOK_DIR/../.." 2>/dev/null || exit 0
# W9-ONCOMMIT-HOOK-CRLF 2026-05-24: strip CR before grep.  Windows git
# emits CRLF line endings in `git log --name-only` output; the `$`
# anchor in `^coord/STATUS\.csv$` doesn't match before \r, so the
# hook fired falsely on every commit that DID touch STATUS.csv.
LAST=$(git log -1 --name-only --pretty='' 2>/dev/null | tr -d '\r')

if echo "$LAST" | grep -q "^coord/STATUS\.csv$"; then
  exit 0
fi

cat >&2 <<'WARN'
Last commit did NOT touch coord/STATUS.csv.

Per feedback_status_csv_canonical.md (memory): STATUS.csv is the canonical
task tracker and must be updated on every task transition. If this commit's
task genuinely doesn't warrant a CSV change, document why in your reply;
otherwise edit STATUS.csv + follow-up commit.
WARN

exit 2
