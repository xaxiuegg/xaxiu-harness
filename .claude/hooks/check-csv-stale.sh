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

# W8-STOP-HOOK 2026-05-23: content-hash + debounce check before find.
# Per 10-reviewer interaction panel (8/10 votes): the hook was firing
# on mtime drift during mutation sweeps, audit-script writes, and any
# tool that touches a file as a side effect.  Six turns this session
# burned on ack-and-touch loops with zero decision value.
#
# Layer 1: if STATUS.csv's content (per git) matches the most recent
# commit AND that commit touched STATUS.csv, the operator just made
# a STATUS update — nothing is stale, exit silently regardless of
# the mtime of other files.  This catches the common case where the
# tool wrote files in a sequence that left STATUS.csv with an older
# mtime than newly-generated review/audit artifacts.
if command -v git >/dev/null 2>&1; then
  cd "D:/xaxiu-harness-standalone" 2>/dev/null || exit 0
  # Get the last commit that touched STATUS.csv, and check whether
  # working-tree STATUS.csv differs.  If unchanged from HEAD, we
  # consider it fresh.
  if git diff --quiet HEAD -- coord/STATUS.csv 2>/dev/null; then
    # Last commit fully captured STATUS.csv content.  Check whether
    # the most recent commit was within 60 minutes — that's the
    # "recent task transition" window the hook cares about.
    last_csv_commit_age_s=$(git log -1 --format=%ct -- coord/STATUS.csv 2>/dev/null)
    if [ -n "$last_csv_commit_age_s" ]; then
      now_s=$(date +%s)
      age_min=$(( (now_s - last_csv_commit_age_s) / 60 ))
      if [ "$age_min" -le 60 ]; then
        exit 0
      fi
    fi
  fi
fi

# W8-STOP-HOOK 2026-05-23: debounce — don't fire more than once per
# 5 minutes regardless of mtime.  State file at .claude/.stop-hook-last
# is a single epoch-seconds timestamp.
DEBOUNCE_FILE="D:/xaxiu-harness-standalone/.claude/.stop-hook-last-fire"
if [ -f "$DEBOUNCE_FILE" ]; then
  last_fire_s=$(cat "$DEBOUNCE_FILE" 2>/dev/null)
  if [ -n "$last_fire_s" ]; then
    now_s=$(date +%s)
    since_last=$(( now_s - last_fire_s ))
    if [ "$since_last" -lt 300 ]; then
      # Fired within last 5 minutes; treat as debounced.
      exit 0
    fi
  fi
fi

# Find any .md / .py / .ps1 / .sh edited in last 60 minutes AND newer than CSV.
# Excludes .git, .swarm audit output, pycache, runs/ workspace output, and
# packet response files which are autonomous dispatch artifacts (not canonical
# task state).  Spec/auto/, coord/reviews/, .pytest_cache/ are also dispatch
# / review artifacts not directly task-state.
#
# W8-AUDIT follow-through 2026-05-24: previously this also -not -path'd the
# mutation-sweep target modules (worker.py / concrete.py / orchestrator.py /
# integrator.py), but the audit caught that as a regression in hook coverage —
# legitimate edits to those files SHOULD fire the hook.  Replaced with the
# per-file git content-hash filter below: if a "recent" file's content matches
# HEAD, it's mtime-only drift (typical of mutation sweep restore-after-apply
# cycles) — skip it.  Real edits will not match HEAD, so they still fire.
CANDIDATES=$(find "D:/xaxiu-harness-standalone" -maxdepth 5 -type f \
  \( -name '*.md' -o -name '*.py' -o -name '*.ps1' -o -name '*.sh' \) \
  -not -path '*/.git/*' \
  -not -path '*/.swarm/*' \
  -not -path '*/__pycache__/*' \
  -not -path '*/.harness/*' \
  -not -path '*/runs/*' \
  -not -path '*/.pytest_cache/*' \
  -not -path '*/coord/packets/*/responses/*' \
  -not -path '*/coord/packets/*/audit/*' \
  -not -path '*/coord/reviews/*' \
  -not -path '*/spec/auto/*' \
  -not -name '*-response.md' \
  -not -name '*-deepseek-*.md' \
  -not -name '*-kimi-*.md' \
  -newer "$CSV" -mmin -60 2>/dev/null)

# Filter out files whose CONTENT matches HEAD (mtime drift only).  Falls back
# to the unfiltered list when git isn't available.
RECENT=""
if command -v git >/dev/null 2>&1; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel="${f#D:/xaxiu-harness-standalone/}"
    if git diff --quiet HEAD -- "$rel" 2>/dev/null; then
      continue
    fi
    RECENT="${RECENT}${f}"$'\n'
  done <<< "$CANDIDATES"
  RECENT=$(printf '%s' "$RECENT" | head -3)
else
  RECENT=$(echo "$CANDIDATES" | head -3)
fi

if [ -z "$RECENT" ]; then
  exit 0
fi

# About to fire — record the debounce timestamp so subsequent fires
# within 5 minutes are suppressed.
mkdir -p "$(dirname "$DEBOUNCE_FILE")" 2>/dev/null
date +%s > "$DEBOUNCE_FILE" 2>/dev/null

cat >&2 <<WARN
Turn-end check: xaxiu-harness/coord/STATUS.csv looks stale relative to other
harness files modified in the last 60 minutes:

$(echo "$RECENT" | sed 's|^|    |')

Per feedback_status_csv_canonical.md (memory): edit STATUS.csv on every task
transition. If you completed work this turn that doesn't fit any tracked row,
either add a new row or document why no update is needed.
WARN

exit 2
