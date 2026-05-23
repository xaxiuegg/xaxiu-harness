#!/usr/bin/env bash
# Stop hook (xaxiu-harness scope). Warns at end-of-turn if coord/STATUS.csv
# is stale relative to other harness files modified this turn.
#
# Mirrors the warehouse hook (D:/Projects/warehouse/.claude/hooks/check-csv-stale.sh)
# but scoped to xaxiu-harness. Per memory feedback_status_csv_canonical.md and
# feedback_active_tracking_table.md — STATUS.csv must reflect every task
# transition (start / complete / defer / new).
#
# Exit 0 = silent pass; exit 2 = emit feedback to Claude.

CSV="D:/xaxiu-harness-standalone/coord/STATUS.csv"

if [ ! -f "$CSV" ]; then
  exit 0
fi

# Scope guard (W6-C1, post-migration 2026-05-22): the project moved from
# D:/Projects/xaxiu-harness/ to D:/xaxiu-harness-standalone/.  Match BOTH
# the new path AND the legacy "xaxiu-harness" substring (so anyone with
# the project at the old path still triggers correctly).
if [[ "$PWD" != *"/xaxiu-harness-standalone"* ]] \
   && [[ "$PWD" != *"/xaxiu-harness"* ]]; then
  exit 0
fi

# Find any .md / .py / .ps1 / .sh edited in last 60 minutes AND newer than CSV.
# Excludes .git, .swarm audit output, pycache, runs/ workspace output, and
# packet response files which are autonomous dispatch artifacts (not canonical
# task state). Coord SESSION_HANDOFF + STATUS.md still count.
RECENT=$(find "D:/xaxiu-harness-standalone" -maxdepth 5 -type f \
  \( -name '*.md' -o -name '*.py' -o -name '*.ps1' -o -name '*.sh' \) \
  -not -path '*/.git/*' \
  -not -path '*/.swarm/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/.harness/*' \
  -not -path '*/runs/*' \
  -not -path '*/coord/packets/*/responses/*' \
  -not -path '*/coord/packets/*/audit/*' \
  -not -path '*/coord/reviews/audits/*' \
  -not -path '*/spec/auto/done/*' \
  -not -name '*-response.md' \
  -not -name '*-deepseek-*.md' \
  -not -name '*-kimi-*.md' \
  -newer "$CSV" -mmin -60 2>/dev/null | head -3)

if [ -z "$RECENT" ]; then
  exit 0
fi

cat >&2 <<WARN
Turn-end check: xaxiu-harness/coord/STATUS.csv looks stale relative to other
harness files modified in the last 60 minutes:

$(echo "$RECENT" | sed 's|^|    |')

Per feedback_status_csv_canonical.md (memory): edit STATUS.csv on every task
transition. If you completed work this turn that doesn't fit any tracked row,
either add a new row or document why no update is needed.
WARN

exit 2
