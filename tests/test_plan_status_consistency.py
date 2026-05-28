"""W14-PLAN-STATUS-CONSISTENCY 2026-05-28: lock the rule that no row
in ``coord/CURRENT_PLAN.md`` "What's next" appears as ``shipped`` in
``coord/STATUS.csv``.

Background — see [feedback_grep_before_declare_greenfield_2026_05_28]
in project memory.

The 2026-05-28 audit found ~50% staleness in CURRENT_PLAN.md
"What's next": W14-PARALLEL-DISPATCH-RETRY-FIX was listed as
unfinished todo while STATUS.csv recorded it as Production shipped
2026-05-26 (with a 168-LOC implementing module).  A strategic agent
grep'ing STATUS.csv for the plan-row name found nothing and
confidently reported "not started" — because shipped row IDs in
STATUS.csv don't always match planning IDs in CURRENT_PLAN.md.

This test fires on the REAL files (``coord/CURRENT_PLAN.md`` and
``coord/STATUS.csv``) so any future drift surfaces in CI.

If this test fails, the fix is to update CURRENT_PLAN.md "What's
next" — either move the shipped row to "Shipped this week" or
delete it.  Do NOT change this test's threshold to make it pass;
that hides the same trust gap that motivated the test.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest


REPO_ROOT: Path = Path(__file__).resolve().parents[1]
CURRENT_PLAN: Path = REPO_ROOT / "coord" / "CURRENT_PLAN.md"
STATUS_CSV: Path = REPO_ROOT / "coord" / "STATUS.csv"


# Row IDs follow the W12/W13/W14/W15 + uppercase-hyphenated convention.
# We catch all four wave prefixes plus the looser WA/WB phase prefixes
# the project also uses (WA1, WB-CONCRETE, etc.).
_ROW_ID_PATTERN = re.compile(
    r"\b(?:W1[2-9]|W[AB]\d?)-[A-Z0-9-]+",
)


def _parse_whats_next_section() -> str:
    """Return the text of the 'What's next' section of CURRENT_PLAN.md.

    The section starts at ``## What's next`` and ends at the next
    horizontal rule (``---`` on its own line) OR end of file.
    """
    text = CURRENT_PLAN.read_text(encoding="utf-8")
    if "## What's next" not in text:
        return ""
    after = text.split("## What's next", 1)[1]
    # End of section: next horizontal rule or end of file
    if "\n---\n" in after:
        after = after.split("\n---\n", 1)[0]
    return after


def _row_ids_in_whats_next() -> set[str]:
    """Extract every WN-* row ID mentioned in the 'What's next' section."""
    return set(_ROW_ID_PATTERN.findall(_parse_whats_next_section()))


def _shipped_status_row_ids() -> set[str]:
    """Row IDs from STATUS.csv where Status column == 'shipped'."""
    ids: set[str] = set()
    with STATUS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("Status") or "").strip().lower() != "shipped":
                continue
            rid = (row.get("ID") or "").strip()
            if rid:
                ids.add(rid)
    return ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParsing:
    def test_whats_next_section_present(self) -> None:
        section = _parse_whats_next_section()
        assert section, (
            "CURRENT_PLAN.md must have a `## What's next` section.  "
            "If you renamed it, update this test to match."
        )

    def test_status_csv_has_shipped_rows(self) -> None:
        ids = _shipped_status_row_ids()
        # Conservative threshold — STATUS.csv has been growing for months
        assert len(ids) >= 50, (
            f"STATUS.csv has only {len(ids)} shipped rows; the file may "
            f"be corrupted or the parser is broken."
        )


class TestConsistency:
    def test_no_shipped_row_appears_in_whats_next(self) -> None:
        """The canonical lock.

        Caught 2026-05-28 audit: W14-PARALLEL-DISPATCH-RETRY-FIX was
        in CURRENT_PLAN.md "Week 2 Operations Hardening" todo list
        AND in STATUS.csv as shipped Production.  Three days stale.
        """
        plan_rows = _row_ids_in_whats_next()
        shipped_rows = _shipped_status_row_ids()
        overlap = plan_rows & shipped_rows
        assert not overlap, (
            f"Rows are in CURRENT_PLAN.md 'What's next' but already "
            f"SHIPPED per STATUS.csv: {sorted(overlap)}.\n\n"
            f"Action: move each of these rows to a 'Shipped this week' "
            f"section or delete from 'What's next.'\n\n"
            f"Do NOT silence this test — the staleness is the bug it's "
            f"catching.  See "
            f"feedback_grep_before_declare_greenfield_2026_05_28 in "
            f"project memory."
        )

    def test_engine_budget_triad_recorded_in_status(self) -> None:
        """Lock today's 4 Tier-1 commits into STATUS.csv.

        Today's 2026-05-28 Tier-1 work shipped four W14 rows.  Assert
        they all landed in STATUS.csv so a future plan-staleness fix
        doesn't accidentally delete one of them.
        """
        shipped = _shipped_status_row_ids()
        expected = {
            "W14-PLAN-RECONCILE-2026-05-28",
            "W14-BUDGET-METER-PER-ENGINE-OBSERVER-HOOK",
            "W14-DISPATCH-HEALTH-AWARE-FALLBACK-IN-ASK-FLOW",
            "W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD",
        }
        missing = expected - shipped
        assert not missing, (
            f"Tier-1 (engine-budget triad) rows missing from STATUS.csv: "
            f"{sorted(missing)}.  Should have landed in commits b503fcb, "
            f"b646b3c, bcb2ae6, 522df36 (2026-05-28)."
        )


class TestAuditFindings:
    """Lock the empirical findings of the 2026-05-28 audit so any
    regression in CURRENT_PLAN.md surfaces as a test failure.

    Each test corresponds to one finding from the audit; they're
    intentionally narrow + named after the row so future maintainers
    know exactly which entry needs attention.
    """

    def test_parallel_dispatch_retry_fix_not_in_whats_next(self) -> None:
        """W14-PARALLEL-DISPATCH-RETRY-FIX shipped 2026-05-26 as a
        168-LOC module + 19 tests + Production STATUS row.  It should
        never reappear in 'What's next' unless renamed.
        """
        section = _parse_whats_next_section()
        assert "W14-PARALLEL-DISPATCH-RETRY-FIX" not in section, (
            "W14-PARALLEL-DISPATCH-RETRY-FIX is back in 'What's next' — "
            "but src/harness/engines/parallel_dispatch.py exists.  "
            "Either rename the plan row or delete it."
        )

    def test_parallel_dispatch_module_exists(self) -> None:
        """Confirm the shipped capability is still in the repo (the
        canonical anchor for the audit row above).
        """
        module = REPO_ROOT / "src" / "harness" / "engines" / "parallel_dispatch.py"
        assert module.exists(), (
            "src/harness/engines/parallel_dispatch.py is missing — "
            "if you deleted it, also update CURRENT_PLAN.md."
        )

    def test_backup_module_exists(self) -> None:
        """W13-BACKUP-RESTORE shipped 2026-05-25.  W14-BACKUP-MANAGER
        in CURRENT_PLAN.md should be renamed/scoped to encryption-only
        (W13-BACKUP-ENCRYPTION) since the rest is already there.
        """
        module = REPO_ROOT / "src" / "harness" / "backup.py"
        assert module.exists(), (
            "src/harness/backup.py is missing — if you deleted it, "
            "the audit row about backup-shipped status is wrong."
        )
