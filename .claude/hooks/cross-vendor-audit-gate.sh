#!/usr/bin/env bash
# cross-vendor-audit-gate.sh  (PreToolUse, matcher: Bash)
#
# HARD-BLOCK: refuse a `git commit` that includes PRODUCTION code
# (src/harness/**.py) unless a recent cross-vendor audit artifact exists.
# Encodes the CLAUDE.md invariant "ship-affecting changes must be verified
# cross-vendor, never by a single Claude session"
# ([feedback_native_features_wire_to_harness], [feedback_no_claude_swarm_worker]).
#
# Scope is deliberately narrow so it never fights trivial work:
#   - fires ONLY on an actual `git commit` invocation
#   - allows unless the commit will include src/harness/**.py (prod code)
#   - allows if a coord/reviews/ask-*/summary.json with mode audit|panel
#     was written in the last 6 hours
#   - escape hatch for a genuinely-trivial prod commit:
#       HARNESS_SKIP_AUDIT_GATE=1 git commit ...
#
# PreToolUse contract: exit 0 = allow; exit 2 = block (stderr shown to Claude).
# We FAIL OPEN (exit 0) on any internal error — a gate that wedges every
# command is worse than no gate; the safe failure mode is "allow".
set -uo pipefail

input="$(cat 2>/dev/null || true)"
cmd="$(printf '%s' "$input" | python -c 'import sys,json
try:
    print((json.load(sys.stdin).get("tool_input") or {}).get("command",""))
except Exception:
    print("")' 2>/dev/null || true)"

# Fire only on an ACTUAL `git commit` invocation — at command start or after a
# shell operator (&& ; |) — NOT a command that merely mentions "git commit".
printf '%s' "$cmd" | grep -qE '(^|[&|;])[[:space:]]*git[[:space:]]+commit([[:space:]]|$)' || exit 0

# Operator escape hatch for trivial prod commits.
[ "${HARNESS_SKIP_AUDIT_GATE:-}" = "1" ] && exit 0

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$root" ] && exit 0                 # not a git repo → not our business
cd "$root" 2>/dev/null || exit 0

# Which production files (src/harness/**.py) will this commit include?
# A plain commit includes only what's already staged; `-a`/`-am`/`--all` and a
# chained `git add` stage more — and PreToolUse fires BEFORE the command runs,
# so widen to the working tree in those cases.  We err toward over-blocking;
# the escape hatch handles the rare false positive (the safe failure mode).
staged="$(git diff --cached --name-only 2>/dev/null | grep -E '^src/harness/.*\.py$' || true)"
prod="$staged"
widen=0
case "$cmd" in
  *"git commit -a"*) widen=1 ;;          # -a / -am (auto-stage tracked mods)
  *--all*)           widen=1 ;;
esac
printf '%s' "$cmd" | grep -qE '(^|[&|;])[[:space:]]*git[[:space:]]+add[[:space:]]' && widen=1
if [ "$widen" = 1 ]; then
  wt="$(git status --porcelain -- src/harness 2>/dev/null | sed 's/^...//' \
        | grep -E '^src/harness/.*\.py$' || true)"
  prod="$(printf '%s\n%s\n' "$staged" "$wt" | grep -E '^src/harness/.*\.py$' | sort -u || true)"
fi
[ -z "$prod" ] && exit 0                  # no prod code in play → allow freely

# Recent (<=6h) cross-vendor audit/panel artifact on record?
recent=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if python -c 'import json,sys
try:
    d=json.load(open(sys.argv[1],encoding="utf-8"))
    sys.exit(0 if d.get("mode") in ("audit","panel") else 1)
except Exception:
    sys.exit(1)' "$f" 2>/dev/null; then
    recent="$f"; break
  fi
done < <(find coord/reviews -name summary.json -mmin -360 2>/dev/null)
[ -n "$recent" ] && exit 0                # cross-vendor verification on record → allow

# Prod commit with no audit on record → BLOCK.
{
  echo "BLOCKED by cross-vendor audit gate."
  echo
  echo "This commit will include production code:"
  printf '%s\n' "$prod" | sed 's/^/    /'
  echo
  echo "…but no cross-vendor audit artifact (coord/reviews/ask-*/summary.json,"
  echo "mode audit|panel) was written in the last 6 hours. Per CLAUDE.md"
  echo "\"Native CC features vs. the harness\", ship-affecting changes must be"
  echo "verified cross-vendor — never by a single Claude session."
  echo
  echo "Do ONE of:"
  echo "  • python -m harness ask \"<what changed + why it is correct>\" --audit"
  echo "    (or delegate to the cross-vendor-panel subagent), then re-commit."
  echo "  • Trivial / non-ship change? HARNESS_SKIP_AUDIT_GATE=1 git commit ..."
} >&2
exit 2
