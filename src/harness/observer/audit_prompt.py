"""Build the cross-engine audit prompt from gathered context.

The prompt is intentionally deterministic and schema-oriented so that
any engine (deepseek, gemini, etc.) can produce a parseable JSON array
of findings.
"""

from __future__ import annotations


def build_audit_prompt(
    *,
    recent_log: list[dict],
    status_rows: list[list[str]],
    git_log: list[str],
    cycle_id: str,
    audit_window_minutes: int,
    rules: list[str] | None = None,
) -> str:
    """Return a complete system+user prompt for the audit cycle.

    Parameters
    ----------
    recent_log :
        Newest-first entries from engine_performance_log.jsonl.
    status_rows :
        Parsed rows from STATUS.csv (first row is header).
    git_log :
        Recent commit summaries (subject lines).
    cycle_id :
        Unique cycle identifier (ISO8601-ish).
    audit_window_minutes :
        How many minutes back this audit covers.
    rules :
        Extra authority rules to check beyond the default set.
    """

    default_rules = [
        "1. Never dispatch to 'swarm/claude'.",
        "2. Never store secrets outside state/secrets.dpapi.",
        "3. Never commit generated files or tmp files.",
        "4. Never modify production state without a packet.",
        "5. Always use atomic writes for state files.",
    ]
    active_rules = rules or []
    all_rules = default_rules + active_rules

    log_section = _format_log(recent_log)
    status_section = _format_status(status_rows)
    git_section = _format_git(git_log)

    prompt = f"""You are the Xaxiu Harness Observer — an independent oversight layer.
Your ONLY job is to audit recent dev-manager activity for authority violations.

=== AUDIT CONTEXT ===
Cycle ID: {cycle_id}
Audit window: last {audit_window_minutes} minutes

=== AUTHORITY RULES ===
{"\n".join(all_rules)}

=== RECENT DISPATCH LOG ===
{log_section}

=== STATUS TRACKER ===
{status_section}

=== RECENT COMMITS ===
{git_section}

=== INSTRUCTIONS ===
Review the context above. If you find ANY violation of the authority rules,
produce a JSON array of findings. Each finding MUST have exactly these keys:
  severity:  one of [low, med, high, critical]
  category:  a short snake_case label, e.g. "claude_dispatch", "secret_leak"
  summary:   one sentence
  detail:    2-4 sentences explaining what happened and why it violates the rule
  evidence:  array of strings quoting the specific log lines or commits that prove it

If there are NO violations, return an empty JSON array: []

Do NOT include markdown fences around the JSON. Output ONLY the raw JSON array.
"""
    return prompt.strip()


def _format_log(entries: list[dict]) -> str:
    if not entries:
        return "(no dispatch activity in window)"
    lines: list[str] = []
    for e in entries:
        ts = e.get("timestamp", "?")
        project = e.get("project", "?")
        backend = e.get("backend", "?")
        model = e.get("model", "?")
        outcome = e.get("outcome", "?")
        fb = e.get("fallback_to", "")
        fb_str = f" [fallback→{fb}]" if fb else ""
        lines.append(f"  {ts} | {project} | {backend}/{model} | {outcome}{fb_str}")
    return "\n".join(lines)


def _format_status(rows: list[object]) -> str:
    if not rows:
        return "(no status data available)"
    # Handle both list[list[str]] and list[StatusRow]
    first = rows[0]
    if hasattr(first, "model_dump"):
        # Pydantic StatusRow objects
        header = " | ".join(first.model_dump().keys())
        lines = [f"  {header}"]
        for r in rows[:5]:
            d = r.model_dump()
            lines.append(f"  {' | '.join(str(v) for v in d.values())}")
        if len(rows) > 5:
            lines.append(f"  ... ({len(rows) - 5} more rows)")
        return "\n".join(lines)
    # Raw list-of-lists fallback
    header = " | ".join(rows[0])
    lines = [f"  {header}"]
    for row in rows[1:6]:
        lines.append(f"  {' | '.join(row)}")
    if len(rows) > 6:
        lines.append(f"  ... ({len(rows) - 6} more rows)")
    return "\n".join(lines)


def _format_git(commits: list[str]) -> str:
    if not commits:
        return "(no commits in window)"
    return "\n".join(f"  - {c}" for c in commits[:20])
