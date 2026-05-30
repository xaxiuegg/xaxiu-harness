"""W11-L5-OUTPUT-CONTRACT: visible L5 escalation output contract.

Per readiness-panel finding: when an L5 fires the operator must
literally SEE the escalation (not just an exit code) and know the
single corrective action.  Today the contract is internal (preflight
emits "FAIL" with explanation; observer raises CRITICAL flag).  This
module provides:

  - render_l5_banner(code, summary, action, evidence?) -> str
      Visually distinct multi-line banner (border + 'L5 ESCALATION'
      header + ACTION callout) ready to print to stdout, the
      dashboard, or an email body.

  - escalation_writeup(code, summary, action, evidence?) -> dict
      JSON-friendly dict for the dashboard / morning-email-brief
      consumers.

  - is_l5(code) -> bool
      Cheap severity check for an L<n>.<domain>.<CODE> tag.

  - should_escalate_to_l5(count, threshold=3) -> bool
      The escalation gate used to decide whether to include an L5
      banner in a restart message.

PATH-A-TRIM 2026-05-29: render_l5_banner + should_escalate_to_l5 are
still used by the core `harness today` / preflight surfaces.
record_restart_outcome was removed — it persisted into the now-deleted
observer state.
"""

from __future__ import annotations

from datetime import datetime, timezone

L5_RESTART_THRESHOLD = 3
_BORDER = "=" * 60


def render_l5_banner(
    code: str, summary: str, action: str, evidence: list[str] | None = None
) -> str:
    """Return a visually distinct banner for an L5 escalation.

    Designed so the operator (often non-technical, per
    [[user_non_technical_role]]) sees the severity and required action
    BEFORE any other log output.  Format:

        ============================================================
        L5 ESCALATION — <code>
        ============================================================
        <summary>

        ACTION: <action>

        Evidence:
          - <ev 1>
          - <ev 2>
        ============================================================
    """
    lines: list[str] = []
    lines.append(_BORDER)
    lines.append(f"L5 ESCALATION — {code}")
    lines.append(_BORDER)
    lines.append(summary)
    lines.append("")
    lines.append(f"ACTION: {action}")
    if evidence:
        lines.append("")
        lines.append("Evidence:")
        for ev in evidence:
            lines.append(f"  - {ev}")
    lines.append(_BORDER)
    return "\n".join(lines)


def escalation_writeup(
    code: str, summary: str, action: str, evidence: list[str] | None = None
) -> dict:
    """Return a JSON-friendly dict for the dashboard banner + email."""
    out: dict = {
        "code": code,
        "severity": "L5",
        "summary": summary,
        "action": action,
        "raised_at": datetime.now(timezone.utc).isoformat(),
    }
    if evidence:
        out["evidence"] = list(evidence)
    return out


def is_l5(code: str) -> bool:
    """True if the tag starts with the L5 severity prefix."""
    if not code:
        return False
    return code.upper().startswith("L5.")


# -- watchdog escalation chain ------------------------------------------


def should_escalate_to_l5(consecutive_failures: int, threshold: int = L5_RESTART_THRESHOLD) -> bool:
    """True when consecutive restart failures meet/exceed the threshold."""
    return consecutive_failures >= threshold
