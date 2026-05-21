"""Recommendation enum and threshold logic."""

from __future__ import annotations

from enum import StrEnum

from harness.session.signals import Signals


class Recommendation(StrEnum):
    NONE = "none"
    SOFT = "soft"
    STRONGLY = "strongly"
    CRITICAL = "critical"


SOFT_SIGNALS = [
    "session_age_soft",
    "tick_count_soft",
    "commits_since_session_soft",
    "status_csv_row_count_soft",
    "jsonl_log_mb_soft",
    "claude_session_jsonl_mb_soft",
]


def _to_recommend_dict(signals: Signals) -> dict[str, object]:
    return {
        "session_age_h": signals.session_age_hours,
        "session_age_soft": signals.session_age_hours > 4,
        "tick_count": signals.tick_count,
        "tick_count_soft": signals.tick_count > 50,
        "commits_since_session": signals.commits_since_session,
        "commits_since_session_soft": signals.commits_since_session > 30,
        "status_csv_row_count": signals.status_csv_row_count,
        "status_csv_row_count_soft": signals.status_csv_row_count > 20,
        "jsonl_log_mb": signals.jsonl_log_mb,
        "jsonl_log_mb_soft": signals.jsonl_log_mb > 50,
        # PRIMARY crash-risk signal (patch 2026-05-21): Claude Code's per-session
        # transcript jsonl size.  Calibrated from operator's historic data —
        # 52MB session crashed; thresholds 8/18/35 give SOFT/STRONGLY/CRITICAL.
        "claude_session_jsonl_mb": signals.claude_session_jsonl_mb,
        "claude_session_jsonl_mb_soft": signals.claude_session_jsonl_mb >= 8,
        "claude_session_jsonl_mb_strongly": signals.claude_session_jsonl_mb >= 18,
        "claude_session_jsonl_mb_critical": signals.claude_session_jsonl_mb >= 35,
        "mem_pct": signals.mem_pct,
        "claude_rss_mb": signals.claude_rss_mb,
        "disk_pct_free": signals.disk_pct_free,
    }


def recommend(signals: Signals) -> tuple[Recommendation, list[str]]:
    """Decide whether to alert the operator and how strongly.

    Returns ``(Recommendation, reasons)``.

    Priority: CRITICAL > STRONGLY > SOFT > NONE.
    The session-transcript jsonl size is the primary crash-risk signal
    (52MB historic crash; thresholds set with safety margin).
    """
    d = _to_recommend_dict(signals)
    reasons: list[str] = []

    # ---- CRITICAL — imminent crash ----
    if d["claude_session_jsonl_mb_critical"]:
        reasons.append(
            f"Session transcript {d['claude_session_jsonl_mb']:.1f}MB >= 35MB "
            f"(approaching 52MB historic-crash territory)"
        )
    if d["mem_pct"] >= 95:
        reasons.append(f"Memory usage {d['mem_pct']}% >= 95%")
    if d["disk_pct_free"] < 5:
        reasons.append(f"Disk free {d['disk_pct_free']:.1f}% < 5%")
    if (
        d["claude_session_jsonl_mb_critical"]
        or d["mem_pct"] >= 95
        or d["disk_pct_free"] < 5
    ):
        return Recommendation.CRITICAL, reasons

    # ---- STRONGLY ("Heavy") — rotate on next checkpoint ----
    if d["claude_session_jsonl_mb_strongly"]:
        reasons.append(
            f"Session transcript {d['claude_session_jsonl_mb']:.1f}MB >= 18MB "
            f"(Heavy / rotate-on-checkpoint threshold)"
        )
    if d["mem_pct"] >= 85:
        reasons.append(f"Memory usage {d['mem_pct']}% >= 85%")
    if d["claude_rss_mb"] > 2048:
        reasons.append(f"Process RSS {d['claude_rss_mb']} MB > 2048 MB")
    if (
        d["claude_session_jsonl_mb_strongly"]
        or d["mem_pct"] >= 85
        or d["claude_rss_mb"] > 2048
    ):
        return Recommendation.STRONGLY, reasons

    # ---- SOFT — informational only; no handoff recommendation ----
    soft_count = sum(1 for s in SOFT_SIGNALS if d.get(s, False))
    if soft_count >= 3:
        triggered = [s for s in SOFT_SIGNALS if d.get(s, False)]
        reasons.append(f"{soft_count} soft thresholds crossed: {', '.join(triggered)}")
    if d["session_age_h"] > 4:
        reasons.append(f"Session age {d['session_age_h']:.1f}h > 4h")
    if d["claude_session_jsonl_mb_soft"]:
        reasons.append(
            f"Session transcript {d['claude_session_jsonl_mb']:.1f}MB >= 8MB "
            f"(soft baseline crossed; informational only)"
        )
    if (
        soft_count >= 3
        or d["session_age_h"] > 4
        or d["claude_session_jsonl_mb_soft"]
    ):
        return Recommendation.SOFT, reasons

    return Recommendation.NONE, reasons
