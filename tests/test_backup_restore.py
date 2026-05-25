"""W13-BACKUP-RESTORE: tests for the harness backup + restore primitives.

Covers the round-trip: backup a runtime state -> wipe it -> restore from
the archive -> verify everything's back.
"""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest


def _seed_repo(repo: Path) -> dict:
    """Create the minimal runtime state structure a backup would capture.

    Returns a dict of the seeded paths so tests can verify round-trip.
    """
    # .harness/dispatched/<id>.json
    (repo / ".harness" / "dispatched").mkdir(parents=True)
    dispatch = repo / ".harness" / "dispatched" / "abc-123.json"
    dispatch.write_text('{"dispatch_id": "abc-123", "text": "hello"}\n',
                         encoding="utf-8")
    # .harness/config.json
    config = repo / ".harness" / "config.json"
    config.write_text('{"project_name": "test"}\n', encoding="utf-8")
    # coord/observer/observer-state.json
    (repo / "coord" / "observer").mkdir(parents=True)
    obs_state = repo / "coord" / "observer" / "observer-state.json"
    obs_state.write_text('{"armed": true}\n', encoding="utf-8")
    # coord/STATUS.csv
    (repo / "coord").mkdir(exist_ok=True)
    status = repo / "coord" / "STATUS.csv"
    status.write_text("ID,Category,Title\nTEST,Test,test row\n",
                       encoding="utf-8")
    # state/engine_health.json (top-level state dir)
    (repo / "state").mkdir()
    eng = repo / "state" / "engine_health.json"
    eng.write_text('{"kimi": {"healthy": true}}\n', encoding="utf-8")
    # Things that should NOT be in the backup:
    env = repo / ".env"
    env.write_text("KIMI_API_KEY=sk-SECRET\n", encoding="utf-8")
    (repo / ".harness" / "worktrees" / "run-1" / "worker-1").mkdir(parents=True)
    (repo / ".harness" / "worktrees" / "run-1" / "worker-1" / "file.txt"
     ).write_text("worktree content", encoding="utf-8")
    return {
        "dispatch": dispatch,
        "config": config,
        "obs_state": obs_state,
        "status": status,
        "eng": eng,
        "env": env,
    }


# -- backup ----------------------------------------------------------------


def test_create_backup_writes_tar_gz(tmp_path):
    from harness import backup as bk
    _seed_repo(tmp_path)
    result = bk.create_backup(repo_root=tmp_path)
    assert result.archive_path.exists()
    assert result.archive_path.suffix == ".gz"
    assert result.archive_path.stat().st_size > 0


def test_create_backup_includes_runtime_state(tmp_path):
    from harness import backup as bk
    seeded = _seed_repo(tmp_path)
    result = bk.create_backup(repo_root=tmp_path)
    with tarfile.open(result.archive_path, "r:gz") as tf:
        names = set(tf.getnames())
    # All expected files are in the archive
    assert ".harness/dispatched/abc-123.json" in names
    assert ".harness/config.json" in names
    assert "coord/observer/observer-state.json" in names
    assert "coord/STATUS.csv" in names
    assert "state/engine_health.json" in names


def test_create_backup_excludes_dotenv(tmp_path):
    """SECURITY: .env must NEVER be in a backup archive."""
    from harness import backup as bk
    _seed_repo(tmp_path)
    result = bk.create_backup(repo_root=tmp_path)
    with tarfile.open(result.archive_path, "r:gz") as tf:
        names = set(tf.getnames())
    # No .env anywhere
    assert not any(".env" in n for n in names), (
        f"backup leaked .env: {[n for n in names if '.env' in n]}"
    )


def test_create_backup_excludes_worktrees(tmp_path):
    """worktrees/ are transient and should be excluded."""
    from harness import backup as bk
    _seed_repo(tmp_path)
    result = bk.create_backup(repo_root=tmp_path)
    with tarfile.open(result.archive_path, "r:gz") as tf:
        names = set(tf.getnames())
    assert not any("worktrees" in n for n in names), (
        f"backup included worktrees: {[n for n in names if 'worktrees' in n]}"
    )


def test_create_backup_embeds_manifest(tmp_path):
    from harness import backup as bk
    _seed_repo(tmp_path)
    result = bk.create_backup(repo_root=tmp_path)
    with tarfile.open(result.archive_path, "r:gz") as tf:
        mfile = tf.extractfile("HARNESS_BACKUP_MANIFEST.json")
        assert mfile is not None
        raw = mfile.read().decode("utf-8")
    data = json.loads(raw)
    assert data["schema_version"] == 1
    assert data["files_count"] >= 5  # at least our 5 seeded paths
    assert "created_at" in data
    assert "paths_included" in data


def test_create_backup_handles_missing_optional_paths(tmp_path):
    """Empty repo: backup should still succeed with manifest + warnings."""
    from harness import backup as bk
    # No _seed_repo call; tmp_path is empty
    result = bk.create_backup(repo_root=tmp_path)
    assert result.archive_path.exists()
    assert result.manifest.files_count == 0


# -- restore ---------------------------------------------------------------


def test_restore_round_trips_seeded_state(tmp_path):
    """End-to-end: seed -> backup -> wipe -> restore -> verify."""
    from harness import backup as bk
    import shutil

    source = tmp_path / "source"
    source.mkdir()
    _seed_repo(source)
    result = bk.create_backup(repo_root=source)
    archive = result.archive_path

    # Wipe everything except the archive (which lives under
    # source/.harness/backups/ — copy it out first)
    archive_copy = tmp_path / archive.name
    shutil.copy(archive, archive_copy)
    shutil.rmtree(source)

    # Restore into a fresh dir
    target = tmp_path / "target"
    target.mkdir()
    restored = bk.restore_backup(archive_copy, repo_root=target)
    assert restored.files_restored >= 5
    assert restored.manifest.schema_version == 1

    # Verify the files came back identically
    assert (target / ".harness" / "config.json").read_text(
        encoding="utf-8") == '{"project_name": "test"}\n'
    assert (target / "coord" / "STATUS.csv").read_text(
        encoding="utf-8") == "ID,Category,Title\nTEST,Test,test row\n"


def test_restore_skips_existing_by_default(tmp_path):
    """By default, restore must NOT overwrite existing files."""
    from harness import backup as bk

    source = tmp_path / "source"
    source.mkdir()
    _seed_repo(source)
    result = bk.create_backup(repo_root=source)

    # Modify the target's config BEFORE restore
    target = tmp_path / "target"
    target.mkdir()
    (target / ".harness").mkdir()
    (target / ".harness" / "config.json").write_text(
        '{"project_name": "MODIFIED"}\n', encoding="utf-8",
    )
    restored = bk.restore_backup(result.archive_path, repo_root=target)
    # config.json was skipped (already existed)
    assert (target / ".harness" / "config.json").read_text(
        encoding="utf-8") == '{"project_name": "MODIFIED"}\n'
    # Skipped files reported as warnings
    assert any(".harness/config.json" in w for w in restored.warnings)


def test_restore_overwrite_flag_replaces_existing(tmp_path):
    from harness import backup as bk

    source = tmp_path / "source"
    source.mkdir()
    _seed_repo(source)
    result = bk.create_backup(repo_root=source)

    target = tmp_path / "target"
    target.mkdir()
    (target / ".harness").mkdir()
    (target / ".harness" / "config.json").write_text(
        '{"project_name": "MODIFIED"}\n', encoding="utf-8",
    )
    bk.restore_backup(result.archive_path, repo_root=target,
                       overwrite_existing=True)
    # Now overwritten
    assert (target / ".harness" / "config.json").read_text(
        encoding="utf-8") == '{"project_name": "test"}\n'


def test_restore_refuses_non_harness_archive(tmp_path):
    """A .tar.gz without HARNESS_BACKUP_MANIFEST.json must be refused."""
    from harness import backup as bk
    bogus = tmp_path / "not-a-harness-backup.tar.gz"
    # Make a tarball with random content + NO manifest
    with tarfile.open(bogus, "w:gz") as tf:
        f = tmp_path / "thing.txt"
        f.write_text("hi", encoding="utf-8")
        tf.add(f, arcname="thing.txt")
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="not a harness backup archive"):
        bk.restore_backup(bogus, repo_root=target)


def test_restore_missing_archive_raises(tmp_path):
    from harness import backup as bk
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(FileNotFoundError):
        bk.restore_backup(tmp_path / "nope.tar.gz", repo_root=target)


def test_restore_refuses_path_traversal(tmp_path):
    """SECURITY: archive entries that escape repo_root must be refused."""
    from harness import backup as bk
    evil = tmp_path / "evil-backup.tar.gz"
    with tarfile.open(evil, "w:gz") as tf:
        # Add a manifest so we get past the prefix check
        from harness.backup import BackupManifest
        from datetime import datetime, timezone
        m = BackupManifest(
            schema_version=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            repo_root=str(tmp_path),
            harness_version="test",
            paths_included=[],
            files_count=0,
            archive_size_bytes=0,
        )
        import io
        mbytes = m.to_json().encode("utf-8")
        info = tarfile.TarInfo(name="HARNESS_BACKUP_MANIFEST.json")
        info.size = len(mbytes)
        tf.addfile(info, io.BytesIO(mbytes))
        # Add a traversing entry
        evil_bytes = b"malicious"
        info2 = tarfile.TarInfo(name="../../etc/passwd")
        info2.size = len(evil_bytes)
        tf.addfile(info2, io.BytesIO(evil_bytes))
    target = tmp_path / "target"
    target.mkdir()
    result = bk.restore_backup(evil, repo_root=target)
    # The traversing entry was refused; warning recorded
    assert any("path-traversing" in w for w in result.warnings)


# -- list + prune ----------------------------------------------------------


def test_list_backups_returns_newest_first(tmp_path):
    import time
    from harness import backup as bk
    _seed_repo(tmp_path)
    # Create 3 backups with deliberate timestamp gaps
    r1 = bk.create_backup(repo_root=tmp_path,
                            archive_name="harness-backup-001.tar.gz")
    time.sleep(0.05)
    r2 = bk.create_backup(repo_root=tmp_path,
                            archive_name="harness-backup-002.tar.gz")
    time.sleep(0.05)
    r3 = bk.create_backup(repo_root=tmp_path,
                            archive_name="harness-backup-003.tar.gz")
    backup_dir = r1.archive_path.parent
    archives = bk.list_backups(backup_dir)
    assert len(archives) == 3
    # Newest first
    assert archives[0].name == "harness-backup-003.tar.gz"
    assert archives[2].name == "harness-backup-001.tar.gz"


def test_prune_keeps_n_most_recent(tmp_path):
    import time
    from harness import backup as bk
    _seed_repo(tmp_path)
    backup_dir = tmp_path / "backups"
    for i in range(15):
        bk.create_backup(repo_root=tmp_path, output_dir=backup_dir,
                           archive_name=f"harness-backup-{i:03d}.tar.gz")
        time.sleep(0.01)
    # Keep 7 dailies + 4 weeklies = 11 most recent
    deleted = bk.prune_old_backups(backup_dir=backup_dir,
                                     keep_dailies=7, keep_weeklies=4)
    remaining = bk.list_backups(backup_dir)
    assert len(remaining) == 11
    assert len(deleted) == 4


def test_prune_no_op_when_under_limit(tmp_path):
    from harness import backup as bk
    _seed_repo(tmp_path)
    backup_dir = tmp_path / "backups"
    bk.create_backup(repo_root=tmp_path, output_dir=backup_dir,
                       archive_name="harness-backup-001.tar.gz")
    deleted = bk.prune_old_backups(backup_dir=backup_dir,
                                     keep_dailies=7, keep_weeklies=4)
    assert deleted == []


# -- CLI -------------------------------------------------------------------


def test_cli_backup_group_registered():
    from harness.cli import cli
    assert "backup" in cli.commands
    backup_grp = cli.commands["backup"]
    sub = set(backup_grp.commands.keys())
    assert {"create", "list", "prune", "restore"} <= sub


def test_cli_backup_create_works(tmp_path, monkeypatch):
    """CLI smoke: `harness backup create` runs without crashing."""
    from click.testing import CliRunner
    from harness.cli import cli
    from harness import backup as bk
    # Patch BOTH the module-level import in harness.backup AND _constants
    # so the CLI command's downstream calls go to tmp_path.
    monkeypatch.setattr(bk, "_REPO_ROOT", tmp_path)
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "config.json").write_text("{}", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["backup", "create"])
    assert result.exit_code == 0, result.output
    assert "archive:" in result.output
    assert ".tar.gz" in result.output


def test_cli_backup_list_empty(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from harness.cli import cli
    from harness import backup as bk
    monkeypatch.setattr(bk, "_REPO_ROOT", tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["backup", "list"])
    assert result.exit_code == 0
    assert "no backups" in result.output.lower()
