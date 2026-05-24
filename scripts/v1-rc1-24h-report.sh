#!/usr/bin/env bash
# v1-rc1-24h-report.sh — operator wake-up report after the 24h autonomous run.
#
# Run this at hour 24+.  Aggregates:
#   - Observer cycle count + flags raised
#   - Dispatches fired + cost spent
#   - L5 escalations
#   - Preflight state at wake
#   - Watchdog verdict
#   - Loop tick history
#   - Any tracebacks in observer logs
#
# Writes the report to coord/reviews/v1-rc1-24h-report.md.

set -e
cd "$(dirname "$0")/.."

REPORT="coord/reviews/v1-rc1-24h-report.md"
mkdir -p coord/reviews

{
  echo "# v1.0.0-rc.1 24-hour autonomous run report"
  echo ""
  echo "**Generated**: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "**Tag**: v1.0.0-rc.1"
  echo "**Spec**: spec/samples/v1-rc1-24h-autonomous-run.md"
  echo ""
  echo "---"
  echo ""

  echo "## Section 1: harness today (last 24h)"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness today --since-hours 24 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 2: Observer cycles"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness observer status 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 3: Watchdog verdict"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness observer watchdog-status 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 4: Cost spent in window"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness cost-today 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 5: Preflight at wake-up"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness preflight --skip-engines 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 6: Preflight check latency over the 24h"
  echo ""
  echo '```'
  PYTHONPATH=src python -m harness preflight-latency --since-hours 24 2>&1 || true
  echo '```'
  echo ""

  echo "## Section 7: L5 escalations (last 24h)"
  echo ""
  if [ -f coord/observer/flags/CRITICAL_FLAG_PENDING.md ]; then
    echo "**CRITICAL flag pending**:"
    echo ""
    echo '```'
    cat coord/observer/flags/CRITICAL_FLAG_PENDING.md
    echo '```'
  else
    echo "  No CRITICAL flag pending."
  fi
  echo ""

  echo "## Section 8: Observer daily retro (if fired)"
  echo ""
  TODAY=$(date -u +%Y-%m-%d)
  if [ -f "coord/observer/daily/${TODAY}.md" ]; then
    echo '```'
    cat "coord/observer/daily/${TODAY}.md"
    echo '```'
  else
    echo "  No daily retro for ${TODAY}.md (cron may not have fired yet)."
  fi
  echo ""

  echo "## Section 9: Git activity in the 24h window"
  echo ""
  echo '```'
  git log --since="24 hours ago" --oneline 2>&1 | head -20 || true
  echo '```'
  echo ""

  echo "## Section 10: Dashboard endpoints health-check"
  echo ""
  echo '```'
  for ep in /api/loop /api/cost /api/preflight-latency /api/l5-events; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8765${ep}" 2>/dev/null || echo "DOWN")
    echo "${ep}: HTTP ${code}"
  done
  echo '```'
  echo ""

  echo "---"
  echo ""
  echo "## Operator next steps"
  echo ""
  echo "Read sections 5 (preflight) and 7 (L5 escalations) FIRST.  If both"
  echo "are clean, the harness carried its first 24h cleanly and v1.0 is"
  echo "ready to promote from RC."
  echo ""
  echo "If preflight FAILED or any L5 fired:"
  echo "1. Read the L5 banner's ACTION line"
  echo "2. Decide: fix in Wave 12-B, defer to Wave 13, or roll back the tag"
  echo "3. Don't ship v1.0 final until preflight is green AND no unaddressed L5"

} > "$REPORT"

echo "Report written to: $REPORT"
echo ""
echo "Quick verdict scan:"
grep -E "Verdict:|status:|cost_max" "$REPORT" | head -10
