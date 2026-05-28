"""W14-REPO-WIDE-STALENESS-AUDIT 2026-05-28: STATUS.csv state corrections.

Applies the 6 row state changes identified by Agent B of the audit
synthesis at coord/reviews/stale-plan-audit-2026-05-28/SYNTHESIS.md.

Each change is documented in-line with the reason — this script is
disposable (one-shot) but the audit trail lives in the diff + commit
message.

Usage:
    python scripts/reconcile_stale_status_rows_2026_05_28.py
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_CSV = REPO_ROOT / "coord" / "STATUS.csv"


# (row_id, new_status, append_to_notes)
CHANGES: list[tuple[str, str, str]] = [
    (
        "W14-KIMI-REPLACEMENT-WITH-GLM",
        "parked",
        " | RECONCILED 2026-05-28: explicitly renamed to "
        "W14-KIMI-REPLACEMENT-WITH-QWEN by W14-ENGINE-COST-USAGE-MATRIX "
        "(2026-05-25); scaffold shipped 2026-05-28 as "
        "W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD. GLM was the original "
        "5th-engine candidate, replaced by Qwen 3.6 Plus per cost-vs-usage "
        "matrix (+34% more capacity at the same $50).",
    ),
    (
        "W14-KIMI-AUTH-RESTORE",
        "shipped",
        " | RECONCILED 2026-05-28: Moonshot walked back the 2026-05-22 "
        "permaban on 2026-05-26; Pattern B path now live via "
        "W14-KIMI-VIA-CLAUDE.  No operator action was ever required.",
    ),
    (
        "W13-PLUGIN-SANDBOX-PLAN",
        "parked",
        " | RECONCILED 2026-05-28: parent plugin architecture explicitly "
        "DROPPED by W13-STRATEGIC-PANEL-15 ('DROP 250-400h of "
        "plugin/multi-user/VPS/best-of-N work').",
    ),
    (
        "W13-VPS-OBSERVER-NAT-PLAN",
        "parked",
        " | RECONCILED 2026-05-28: parent W17-VPS-OBSERVER feature "
        "DROPPED by W13-STRATEGIC-PANEL-15; no W17 rows exist anywhere.",
    ),
    (
        "W13-BEST-OF-N-COST-CAP",
        "parked",
        " | RECONCILED 2026-05-28: parent W14-BEST-OF-N DROPPED by "
        "W13-STRATEGIC-PANEL-15; generic per-engine cap shipped as "
        "W14-BUDGET-METER-PER-ENGINE-OBSERVER-HOOK 2026-05-28.",
    ),
    (
        "W12-B-MAX-TOKENS-DEFAULT-RAISE",
        "partial",
        " | RECONCILED 2026-05-28: 3 of 4 sub-items shipped via "
        "W15-ENGINE-FIXES + W5-W + W7-KIMI-MAX-TOKENS-FLOOR + "
        "W13-SDK-REVIEW-AND-CAPABILITIES; only the 3 script caps in "
        "scripts/{review_aquinas_brief,audit_w_action_panel20,"
        "operator_review_panel20}.py still hold 1500-2000 caps.  "
        "Remaining work: ~15min, not ~2h.",
    ),
]


def main() -> int:
    if not STATUS_CSV.exists():
        print(f"ERROR: {STATUS_CSV} not found")
        return 1

    rows: list[dict[str, str]] = []
    with STATUS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    if not fieldnames:
        print("ERROR: STATUS.csv has no header")
        return 1

    # Index by ID for fast lookup.
    by_id = {r["ID"]: r for r in rows if r.get("ID")}

    applied: list[str] = []
    skipped: list[str] = []

    for row_id, new_status, append_note in CHANGES:
        if row_id not in by_id:
            skipped.append(f"{row_id}: NOT FOUND in STATUS.csv")
            continue
        row = by_id[row_id]
        old_status = row.get("Status", "?")
        # Don't blindly overwrite shipped rows
        if old_status.strip().lower() == "shipped" and new_status != "shipped":
            skipped.append(
                f"{row_id}: already shipped, refusing to demote to {new_status}"
            )
            continue
        row["Status"] = new_status
        # Append the reconciliation note
        row["Notes"] = (row.get("Notes", "") or "") + append_note
        applied.append(f"{row_id}: {old_status} → {new_status}")

    # Atomic write via tempfile
    tmp = STATUS_CSV.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    # Backup the original
    backup = STATUS_CSV.with_suffix(".csv.bak")
    shutil.copyfile(STATUS_CSV, backup)
    tmp.replace(STATUS_CSV)

    print(f"Applied {len(applied)} changes:")
    for change in applied:
        print(f"  - {change}")
    if skipped:
        print(f"\nSkipped {len(skipped)}:")
        for skip in skipped:
            print(f"  - {skip}")
    print(f"\nBackup written to {backup} (delete after verifying diff)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
