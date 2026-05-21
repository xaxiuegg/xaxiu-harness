"""Atomic read/write/summary/verify for STATUS.csv."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from harness.coord.lockfile import file_lock
from harness.errors import StateLockTimeout
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


_MIN_FREE_BYTES = 10 * 1024 * 1024  # 10 MB — refuses write below this floor


def _check_disk_space(target_dir: Path, needed_bytes: int = _MIN_FREE_BYTES) -> None:
    """Raise OSError when target_dir has less than needed_bytes free.

    DISK-FULL-GUARD (2026-05-21): pre-flight check so the write fails fast
    with a clear error message instead of producing a truncated CSV that
    corrupts the canonical STATUS.csv.
    """
    import shutil as _shutil
    try:
        stat = _shutil.disk_usage(str(target_dir))
    except OSError as exc:
        # If we can't measure free space, don't block the write
        return
    if stat.free < needed_bytes:
        raise OSError(
            f"insufficient disk space at {target_dir}: "
            f"{stat.free} bytes free < {needed_bytes} required"
        )


def _sha256_of(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_status(path: Path, rows: list[StatusRow]) -> None:
    """Atomically overwrite *path* with *rows*.

    Uses ``csv.DictWriter`` with QUOTE_MINIMAL so any comma in Notes is
    properly quoted.  Atomic via ``tempfile.mkstemp`` + ``os.replace``;
    original file is untouched on any failure, and no temp file is left
    behind regardless of which step raised.

    DISK-FULL-GUARD (2026-05-21):
    1. Pre-flight disk space check refuses write below 10 MB free.
    2. After ``os.replace`` we read the new file back and verify the
       in-memory SHA matches — guards against half-written CSV.
    3. The previous successful contents are kept at ``<path>.bak`` so
       the operator (or a recovery script) can restore on detection of
       corruption.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path) as ok:
        if not ok:
            raise StateLockTimeout(f"could not acquire lock on {path} within timeout")
        # 1. Pre-flight disk-space check
        _check_disk_space(path.parent)

        # 2. Rotate current file to .bak (best-effort — first-write OK with no .bak)
        bak_path = path.with_suffix(path.suffix + ".bak")
        if path.exists():
            try:
                import shutil as _shutil
                _shutil.copy2(path, bak_path)
            except OSError:
                pass  # bak is best-effort

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
            # 3. Capture pre-replace SHA of the temp file
            tmp_sha = _sha256_of(tmp_path)
            os.replace(tmp_path, path)
            # 4. Post-replace SHA verify — corrupted write detected here
            post_sha = _sha256_of(path)
            if post_sha != tmp_sha:
                # Restore from .bak if we have one
                if bak_path.exists():
                    try:
                        import shutil as _shutil
                        _shutil.copy2(bak_path, path)
                    except OSError:
                        pass
                raise OSError(
                    f"STATUS write corruption detected: "
                    f"expected SHA {tmp_sha[:12]} got {post_sha[:12]}"
                )
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
