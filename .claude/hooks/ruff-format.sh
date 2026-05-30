#!/usr/bin/env bash
# PostToolUse(Edit|Write|MultiEdit) hook: auto-format Python on edit with ruff.
# Reads the Claude Code hook JSON on stdin, extracts tool_input.file_path, and if it's a
# .py file, runs `ruff format` + `ruff check --fix` on it. Best-effort + silent — NEVER
# blocks or fails the edit (exit 0 always); ruff config comes from pyproject.toml [tool.ruff].
INPUT=$(cat 2>/dev/null || true)

# Extract the edited file path (python is always present in this project's env; jq may not be).
FILE=$(printf '%s' "$INPUT" | python -c "import sys,json
try:
    d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('file_path','') or '')
except Exception:
    print('')" 2>/dev/null)

[ -z "$FILE" ] && exit 0
case "$FILE" in
  *.py) ;;        # only Python files
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0

# Prefer the `ruff` on PATH; fall back to `python -m ruff`. Quiet + non-fatal.
if command -v ruff >/dev/null 2>&1; then
  ruff format "$FILE"      >/dev/null 2>&1 || true
  ruff check --fix "$FILE" >/dev/null 2>&1 || true
else
  python -m ruff format "$FILE"      >/dev/null 2>&1 || true
  python -m ruff check --fix "$FILE" >/dev/null 2>&1 || true
fi
exit 0
