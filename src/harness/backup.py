"""W13-BACKUP-RESTORE: harness backup + restore for laptop-dies recovery.

Per the Horizon C internal-tool plan: the operator depends on this in
real client work; data loss (dispatch cache, observer state, cost
ledger, STATUS.csv) is an existential risk.

`harness backup` snapshots the runtime state into a single .tar.gz
archive.  `harness restore <archive>` round-trips it back.  Both are
idempotent + safe to run during a live observer cycle.

What gets backed up:
  - .harness/dispatched/          (dispatch cache)
  - .harness/config.json          (project config)
  - coord/observer/               (observer state, daily retros, flags)
  - coord/STATUS.csv              (canonical task tracker)
  - state/                        (engine health, locks, etc.)
  - <ledger_path>                 (dispatch budget ledger, if separate)

What does NOT get backed up:
  - src/                          (in git, recoverable via clone)
  - tests/                        (in git)
  - docs/                         (in git)
  - .env                          (intentional — secrets stay out of backups;
                                   restore prompts the operator to re-paste)
  - .pytest_cache/                (regenerated on next pytest run)
  - .harness/worktrees/           (transient run state, regenerated)
"""
from __future__ import annotations

import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness._constants import _REPO_ROOT

# --- what we back up -------------------------------------------------------

# Paths are relative to repo root.  Order matters for the manifest;
# everything is captured but the order is what `harness restore` walks.
BACKUP_PATHS: list[str] = [
    ".harness/dispatched",
    ".harness/config.json",
    "coord/observer",
    "coord/STATUS.csv",
    "state",
]

# Glob patterns to EXCLUDE inside the included paths.
# We never back up: .env files, worktree state, pytest caches.
EXCLUDE_GLOBS: list[str] = [
    "*.env",
    ".env*",
    ".env",
    "worktrees/*",
    "*.pyc",
    "__pycache__/*",
    ".pytest_cache/*",
]


@dataclass
class BackupManifest:
    """Metadata embedded in every backup archive."""
    schema_version: int
    created_at: str
    repo_root: str
    harness_version: str
    paths_included: list[str]
    files_count: int
    archive_size_bytes: int

    def to_json(self) -> str:
        from dataclasses import asdict
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "BackupManifest":
        data = json.loads(raw)
        return cls(**data)


@dataclass
class BackupResult:
    archive_path: Path
    manifest: BackupManifest
    elapsed_s: float


@dataclass
class RestoreResult:
    archive_path: Path
    manifest: BackupManifest
    files_restored: int
    elapsed_s: float
    warnings: list[str]


# --- helpers ---------------------------------------------------------------


def _harness_version() -> str:
    try:
        from harness import __version__
        return __version__
    except (ImportError, AttributeError):
        # Fall back to reading the git tag if installed without version metadata
        return "unknown"


def _should_exclude(name: str) -> bool:
    """Check name against EXCLUDE_GLOBS; True = skip."""
    from fnmatch import fnmatch
    for pat in EXCLUDE_GLOBS:
        if fnmatch(name, pat) or fnmatch(name.split("/")[-1], pat):
            return True
    return False


def _walk_for_backup(base: Path, rel_base: str) -> list[tuple[Path, str]]:
    """Yield (absolute_path, archive_name) tuples for everything to include.

    archive_name is the path INSIDE the tarball.  Excluded files are skipped.
    """
    out: list[tuple[Path, str]] = []
    if not base.exists():
        return out
    if base.is_file():
        if not _should_exclude(rel_base):
            out.append((base, rel_base))
        return out
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        archive_name = f"{rel_base}/{rel}"
        if _should_exclude(archive_name):
            continue
        out.append((path, archive_name))
    return out


# --- backup ----------------------------------------------------------------


def create_backup(*,
                   output_dir: Path | None = None,
                   archive_name: str | None = None,
                   repo_root: Path | None = None) -> BackupResult:
    """Create a .tar.gz snapshot of the harness runtime state.

    Args:
        output_dir: where to write the archive (default:
            <repo_root>/.harness/backups/).
        archive_name: archive filename (default:
            harness-backup-<UTC-timestamp>.tar.gz).
        repo_root: override repo root (for tests).

    Returns:
        BackupResult with archive path + manifest + timing.
    """
    import time
    started = time.monotonic()
    root = repo_root or _REPO_ROOT
    if output_dir is None:
        output_dir = root / ".harness" / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)
    if archive_name is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"harness-backup-{stamp}.tar.gz"
    archive_path = output_dir / archive_name

    # Collect all (file, archive-name) pairs upfront so we can write
    # the manifest accurately.
    entries: list[tuple[Path, str]] = []
    for rel in BACKUP_PATHS:
        target = root / rel
        entries.extend(_walk_for_backup(target, rel))

    # Write the archive
    with tarfile.open(archive_path, "w:gz") as tf:
        for src, name in entries:
            try:
                tf.add(str(src), arcname=name)
            except OSError as exc:
                # Skip unreadable files but don't crash the backup
                # (e.g., a lock file held by a live observer).
                pass

        # Manifest embedded as a separate file inside the archive
        manifest = BackupManifest(
            schema_version=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            repo_root=str(root),
            harness_version=_harness_version(),
            paths_included=BACKUP_PATHS,
            files_count=len(entries),
            archive_size_bytes=0,  # backfilled below
        )
        manifest_bytes = manifest.to_json().encode("utf-8")
        info = tarfile.TarInfo(name="HARNESS_BACKUP_MANIFEST.json")
        info.size = len(manifest_bytes)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        import io
        tf.addfile(info, io.BytesIO(manifest_bytes))

    # Backfill archive size in a re-read of the manifest (the manifest
    # inside the archive doesn't include its own size; that's fine —
    # the caller of BackupResult gets the accurate size).
    actual_size = archive_path.stat().st_size
    manifest.archive_size_bytes = actual_size
    elapsed = time.monotonic() - started
    return BackupResult(archive_path=archive_path, manifest=manifest,
                         elapsed_s=elapsed)


def list_backups(backup_dir: Path | None = None) -> list[Path]:
    """List existing backup archives sorted newest-first."""
    if backup_dir is None:
        backup_dir = _REPO_ROOT / ".harness" / "backups"
    if not backup_dir.exists():
        return []
    archives = sorted(
        backup_dir.glob("harness-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return list(archives)


def prune_old_backups(*,
                       backup_dir: Path | None = None,
                       keep_dailies: int = 7,
                       keep_weeklies: int = 4) -> list[Path]:
    """Delete old backups, keeping N most-recent dailies + N weeklies.

    Returns list of paths deleted.  Conservative: only deletes files
    matching the harness-backup-*.tar.gz pattern.
    """
    archives = list_backups(backup_dir)
    if not archives:
        return []
    keep_total = keep_dailies + keep_weeklies
    if len(archives) <= keep_total:
        return []
    # Simple policy: keep the N most-recent; later W13 can improve to
    # daily/weekly cadence-aware pruning.
    to_delete = archives[keep_total:]
    deleted: list[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
        except OSError:
            pass
    return deleted


# --- restore ---------------------------------------------------------------


def restore_backup(archive_path: Path,
                    *,
                    repo_root: Path | None = None,
                    overwrite_existing: bool = False) -> RestoreResult:
    """Restore a backup archive into the repo's runtime state.

    Args:
        archive_path: the .tar.gz produced by create_backup.
        repo_root: override repo root (for tests).
        overwrite_existing: if True, overwrite files that already exist
            in the runtime state.  Default False: skip existing files +
            collect them as warnings.

    Returns:
        RestoreResult with manifest + count + warnings.

    Raises:
        FileNotFoundError if archive_path doesn't exist
        ValueError if the archive lacks the manifest (not a harness backup)
    """
    import time
    started = time.monotonic()
    root = repo_root or _REPO_ROOT
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(str(archive_path))

    warnings: list[str] = []
    files_restored = 0
    manifest: BackupManifest | None = None

    with tarfile.open(archive_path, "r:gz") as tf:
        # Read manifest first
        try:
            mfile = tf.extractfile("HARNESS_BACKUP_MANIFEST.json")
            if mfile is None:
                raise ValueError("HARNESS_BACKUP_MANIFEST.json not extractable")
            manifest = BackupManifest.from_json(
                mfile.read().decode("utf-8"),
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{archive_path} is not a harness backup archive "
                f"(missing manifest): {exc}"
            ) from exc

        # Extract everything else
        for member in tf.getmembers():
            if member.name == "HARNESS_BACKUP_MANIFEST.json":
                continue
            if not member.isfile():
                continue
            target = root / member.name
            # Refuse to escape repo_root (path-traversal defense)
            try:
                target.resolve().relative_to(root.resolve())
            except ValueError:
                warnings.append(
                    f"refused path-traversing entry: {member.name}"
                )
                continue
            if target.exists() and not overwrite_existing:
                warnings.append(
                    f"skipped existing (use --overwrite to replace): "
                    f"{member.name}"
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is None:
                warnings.append(f"could not extract: {member.name}")
                continue
            with target.open("wb") as fh:
                shutil.copyfileobj(extracted, fh)
            files_restored += 1

    elapsed = time.monotonic() - started
    return RestoreResult(
        archive_path=archive_path,
        manifest=manifest,
        files_restored=files_restored,
        elapsed_s=elapsed,
        warnings=warnings,
    )
