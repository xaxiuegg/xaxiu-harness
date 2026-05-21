"""Atomic read/write/summary/verify for STATUS.csv."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from harness.status.schema import Status, StatusRow

DEFAULT_STATUS_PATH: Path = Path("coord/STATUS.csv")

_FIELD_MAP = {
    "ID": "id",
    "Category": "category",
    "Title": "title",
    "Status": "status",
    "Owner": "owner",
    "Effort": "effort",
    "Updated": "updated",
    "Notes": "notes",
}

_REVERSE_FIELD_MAP = {v: k for k, v in _FIELD_MAP.items()}

_HEADER = list(_FIELD_MAP.keys())


def _today() -> str:
    """Return today's date in UTC as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_status(path: Path) -> list[StatusRow]:
    """Read and validate *path* as a STATUS.csv.

    Tolerates rows with extra (unquoted-comma) fields by appending the
    overflow back into the Notes column rather than dropping it.  Strict
    schema validation runs on the merged result.
    """
    if not path.exists():
        return []
    rows: list[StatusRow] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for line_num, raw in enumerate(reader, start=2):
            if raw is None:
                continue
            extras = raw.pop(None, None)
            mapped: dict[str, str] = {}
            for k, v in raw.items():
                if k is None or not isinstance(v, str):
                    continue
                mapped[_FIELD_MAP.get(k, k)] = v.strip()
            if extras:
                merged_extra = ",".join(
                    str(x).strip() for x in extras if x is not None
                )
                existing_notes = mapped.get("notes", "")
                mapped["notes"] = (
                    f"{existing_notes},{merged_extra}" if existing_notes else merged_extra
                )
            try:
                rows.append(StatusRow.model_validate(mapped))
            except Exception as exc:
                raise ValueError(
                    f"Row {line_num} validation failed: {exc}"
                ) from exc
    return rows


def write_status(path: Path, rows: list[StatusRow]) -> None:
    """Atomically overwrite *path* with *rows*.

    Uses ``csv.DictWriter`` with QUOTE_MINIMAL so any comma in Notes is
    properly quoted.  Atomic via ``tempfile.mkstemp`` + ``os.replace``;
    original file is untouched on any failure, and no temp file is left
    behind regardless of which step raised.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".status_")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_HEADER, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                data = row.model_dump(mode="json")
                mapped = {
                    csv_col: data.get(attr, "")
                    for csv_col, attr in _FIELD_MAP.items()
                }
                writer.writerow(mapped)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def add_row(path: Path, row: StatusRow) -> None:
    """Append *row* to *path*."""
    rows = read_status(path)
    if any(r.id == row.id for r in rows):
        raise ValueError(f"Row with id '{row.id}' already exists")
    rows.append(row)
    write_status(path, rows)


def update_row(path: Path, row_id: str, **fields: str) -> StatusRow:
    """Update fields on the row matching *row_id* and persist."""
    rows = read_status(path)
    for i, r in enumerate(rows):
        if r.id == row_id:
            data = r.model_dump(mode="json")
            for key, value in fields.items():
                if key == "status":
                    data[key] = Status(value).value
                else:
                    data[key] = value
            data["updated"] = _today()
            updated = StatusRow.model_validate(data)
            rows[i] = updated
            write_status(path, rows)
            return updated
    raise KeyError(f"Row with id '{row_id}' not found")


def summary(path: Path) -> dict[Status, int]:
    """Return counts per status."""
    rows = read_status(path)
    counts: dict[Status, int] = {s: 0 for s in Status}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def verify(path: Path, expected_cadence_minutes: int | None = None) -> list[str]:
    """Validate all rows and flag stale or stuck in_progress tasks."""
    issues: list[str] = []
    raw_rows: list[dict[str, str]] = []

    if not path.exists():
        return ["File does not exist"]

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for line_num, raw in enumerate(reader, start=2):
            if raw is None:
                continue
            mapped = {
                _FIELD_MAP.get(k, k): v.strip() if v else ""
                for k, v in raw.items()
            }
            mapped = {k: v for k, v in mapped.items() if k}
            raw_rows.append(mapped)
            try:
                StatusRow.model_validate(mapped)
            except Exception as exc:
                issues.append(
                    f"Row {line_num} ({mapped.get('id', '?')}): {exc}"
                )

    in_progress_rows = [
        r for r in raw_rows if r.get("status") == "in_progress"
    ]

    # Stale file detection
    if expected_cadence_minutes is not None:
        mtime = path.stat().st_mtime
        now = datetime.now(timezone.utc).timestamp()
        threshold = expected_cadence_minutes * 2 * 60
        if (now - mtime) > threshold and in_progress_rows:
            issues.append(
                f"STATUS.csv is stale (mtime > {expected_cadence_minutes * 2} min) "
                f"with {len(in_progress_rows)} in_progress row(s)"
            )

        # Stuck row detection: in_progress with updated date older than today
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for raw in in_progress_rows:
            updated = raw.get("updated", "-")
            if updated != "-" and updated < today_str:
                issues.append(
                    f"Row {raw.get('id', '?')} is in_progress but last updated {updated}"
                )

    return issues
