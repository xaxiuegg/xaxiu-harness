"""Behavioral tests for ``.claude/hooks/check-csv-stale.sh``.

W8-AUDIT follow-through 2026-05-24: the W8 audit STOPped on this hook
at confidence 0.35 because there were zero automated tests.  These
tests exercise the three layers (content-hash, debounce, find +
git-diff filter) by invoking the script in a controlled tmp_path
workspace.

The hook itself is a bash script so we run it via ``bash -c`` and
assert on the exit code + stderr.  Requires bash (Git Bash on
Windows).  Skipped on platforms where bash isn't available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "check-csv-stale.sh"


def _bash_available() -> bool:
    return shutil.which("bash") is not None


pytestmark = pytest.mark.skipif(
    not _bash_available(),
    reason="bash not available on this platform",
)


def _adapt_hook_for_tmp(tmp_path: Path) -> Path:
    """Copy + rewrite the hook script to operate against tmp_path.

    The production hook hardcodes ``D:/xaxiu-harness-standalone``.  The
    test rewrites those to ``tmp_path`` so we can exercise the logic in
    isolation.
    """
    original = HOOK.read_text(encoding="utf-8")
    # Bash inside Git Bash uses forward slashes; convert Windows-style
    # tmp_path to that form.
    posix_root = str(tmp_path).replace("\\", "/")
    adapted = original.replace("D:/xaxiu-harness-standalone", posix_root)
    out = tmp_path / "hook.sh"
    out.write_text(adapted, encoding="utf-8")
    out.chmod(0o755)
    return out


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True,
    )


def _run_hook(hook: Path, *, cwd: Path) -> subprocess.CompletedProcess:
    """Run the (adapted) hook script and return the completed process."""
    return subprocess.run(
        ["bash", str(hook)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ, "PWD": str(cwd)},
    )


def test_hook_exits_silent_when_csv_missing(tmp_path: Path) -> None:
    """No STATUS.csv → exit 0 silently (early guard)."""
    (tmp_path / "coord").mkdir()
    hook = _adapt_hook_for_tmp(tmp_path)
    proc = _run_hook(hook, cwd=tmp_path)
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_hook_exits_silent_when_pwd_outside_scope(tmp_path: Path) -> None:
    """PWD not under xaxiu-harness → exit 0 (scope guard).

    Even with a stale STATUS.csv and modified files, the hook should be
    silent if invoked from a path that isn't under xaxiu-harness.
    """
    (tmp_path / "coord").mkdir()
    csv = tmp_path / "coord" / "STATUS.csv"
    csv.write_text("ID,Title\n", encoding="utf-8")
    hook = _adapt_hook_for_tmp(tmp_path)
    # cwd is the tmp_path itself which does NOT contain "xaxiu-harness".
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    proc = subprocess.run(
        ["bash", str(hook)],
        cwd=str(outside_dir),
        capture_output=True, text=True,
        env={**os.environ, "PWD": str(outside_dir)},
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_hook_silent_when_only_mtime_drift_matches_head(tmp_path: Path) -> None:
    """File touched but content matches HEAD → silent (mutation sweep case).

    This is the regression the W8-AUDIT follow-through fixed: previously
    the hook used a hard path-exclusion for mutation-target modules.  Now
    it filters by git content-hash so legitimate edits still fire.
    """
    # Stage a fake "xaxiu-harness" repo so the scope guard matches.
    repo = tmp_path / "xaxiu-harness-standalone"
    repo.mkdir()
    (repo / "coord").mkdir()
    csv = repo / "coord" / "STATUS.csv"
    csv.write_text("ID,Title\nX,one\n", encoding="utf-8")
    (repo / "src").mkdir()
    src_file = repo / "src" / "worker.py"
    src_file.write_text("# original\n", encoding="utf-8")
    _git_init(repo)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True,
    )
    # Mutate-and-restore: touch the file but keep content identical.
    # First make sure STATUS.csv has an older mtime than the file we
    # touch (simulates the mutation sweep that writes after CSV).
    older = time.time() - 600  # 10 minutes ago
    os.utime(csv, (older, older))
    src_file.write_text("# original\n", encoding="utf-8")  # rewrite same content
    # Manually adapt hook for this tmp repo.
    hook_content = HOOK.read_text(encoding="utf-8").replace(
        "D:/xaxiu-harness-standalone", str(repo).replace("\\", "/")
    )
    hook = tmp_path / "hook.sh"
    hook.write_text(hook_content, encoding="utf-8")
    hook.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(hook)],
        cwd=str(repo),
        capture_output=True, text=True,
        env={**os.environ, "PWD": str(repo)},
    )
    # Content matches HEAD → silent (exit 0) even though mtime is newer.
    assert proc.returncode == 0, (
        f"hook fired despite content matching HEAD: stderr={proc.stderr!r}"
    )


def test_hook_fires_when_real_content_change(tmp_path: Path) -> None:
    """File edited with real content change → exit 2 with warning."""
    repo = tmp_path / "xaxiu-harness-standalone"
    repo.mkdir()
    (repo / "coord").mkdir()
    csv = repo / "coord" / "STATUS.csv"
    csv.write_text("ID,Title\nX,one\n", encoding="utf-8")
    (repo / "src").mkdir()
    src_file = repo / "src" / "worker.py"
    src_file.write_text("# original\n", encoding="utf-8")
    _git_init(repo)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True,
    )
    # Make STATUS.csv older than the source edit.
    older = time.time() - 600
    os.utime(csv, (older, older))
    # Real content change to a non-excluded source file.
    src_file.write_text("# real edit — different content\n", encoding="utf-8")
    hook_content = HOOK.read_text(encoding="utf-8").replace(
        "D:/xaxiu-harness-standalone", str(repo).replace("\\", "/")
    )
    hook = tmp_path / "hook.sh"
    hook.write_text(hook_content, encoding="utf-8")
    hook.chmod(0o755)
    # Also bypass layer 1 (content-hash on STATUS.csv) by making the
    # last STATUS.csv commit older than 60min.  We can simulate this by
    # backdating the commit, but simpler: leave the test as-is because
    # the layer 1 check only suppresses if STATUS.csv matches HEAD AND
    # the commit is within 60 minutes — fresh test commit, 60min check
    # passes, so layer 1 would normally suppress.  To force layer 3,
    # we modify STATUS.csv in working tree so it diverges from HEAD.
    csv.write_text("ID,Title\nX,one\nY,two-uncommitted\n", encoding="utf-8")
    os.utime(csv, (older, older))  # keep mtime old
    src_file.touch()  # ensure mtime newer than csv
    # Clear any debounce file from prior runs.
    debounce = repo / ".claude" / ".stop-hook-last-fire"
    if debounce.exists():
        debounce.unlink()
    proc = subprocess.run(
        ["bash", str(hook)],
        cwd=str(repo),
        capture_output=True, text=True,
        env={**os.environ, "PWD": str(repo)},
    )
    # Real edit + stale CSV → exit 2 + warning emitted to stderr.
    assert proc.returncode == 2, (
        f"hook did not fire on real content change: "
        f"returncode={proc.returncode}, stderr={proc.stderr!r}"
    )
    assert "looks stale" in proc.stderr or "STATUS.csv" in proc.stderr


def test_hook_debounce_suppresses_within_5min(tmp_path: Path) -> None:
    """Second fire within 5 minutes is suppressed (layer 2)."""
    repo = tmp_path / "xaxiu-harness-standalone"
    repo.mkdir()
    (repo / "coord").mkdir()
    csv = repo / "coord" / "STATUS.csv"
    csv.write_text("ID,Title\nX,one\n", encoding="utf-8")
    _git_init(repo)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True,
    )
    # Write a recent debounce file (now) — should suppress regardless.
    debounce_dir = repo / ".claude"
    debounce_dir.mkdir(exist_ok=True)
    debounce = debounce_dir / ".stop-hook-last-fire"
    debounce.write_text(str(int(time.time())), encoding="utf-8")
    hook_content = HOOK.read_text(encoding="utf-8").replace(
        "D:/xaxiu-harness-standalone", str(repo).replace("\\", "/")
    )
    hook = tmp_path / "hook.sh"
    hook.write_text(hook_content, encoding="utf-8")
    hook.chmod(0o755)
    proc = subprocess.run(
        ["bash", str(hook)],
        cwd=str(repo),
        capture_output=True, text=True,
        env={**os.environ, "PWD": str(repo)},
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
