"""W9-ONCOMMIT-HOOK-CRLF: regression tests for the post-commit STATUS.csv hook.

The hook (.claude/hooks/check-csv-on-commit.sh) fires after every Bash
tool invocation containing 'git commit' inside the xaxiu-harness
project.  Pre-W9 the hook had a CRLF false-positive bug — Windows git
emits CRLF in `git log --name-only` output, and the original grep
anchor `^coord/STATUS.csv$` couldn't match before \\r, so the hook
fired even on commits that DID touch STATUS.csv.

These tests exercise the hook's match logic through controlled
stdin/git input.  The hook itself shells to bash; tests are skipped
gracefully when bash isn't available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "check-csv-on-commit.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None,
    reason="bash not available — hook is a bash script",
)


def _run_hook_with_fake_git(*, git_log_stdout: str,
                            stdin_payload: str) -> subprocess.CompletedProcess:
    """Invoke the hook with a shimmed `git` that returns *git_log_stdout*.

    The shim is a one-off bash function via PATH override: we put a
    temporary dir with our fake `git` executable at the front of PATH.

    *git_log_stdout* is written verbatim (bytes, including any \\r) to
    a file that the shim `cat`s — printf escape interpretation would
    eat our controlled CR characters.
    """
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="hooktest_")
    try:
        # Stash the exact bytes we want git to emit
        canned = Path(tmpdir) / "canned.txt"
        canned.write_bytes(git_log_stdout.encode("utf-8"))
        # Fake git that just cats the canned file (ignores all args)
        git_shim = Path(tmpdir) / "git"
        # Use bash to cat the file with bash-friendly Unix path
        canned_unix = str(canned).replace("\\", "/")
        shim_src = (
            "#!/usr/bin/env bash\n"
            f"cat '{canned_unix}'\n"
        )
        git_shim.write_text(shim_src, encoding="utf-8")
        git_shim.chmod(0o755)

        env = {
            **os.environ,
            "PATH": f"{tmpdir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        proc = subprocess.run(
            [BASH, str(HOOK)],
            input=stdin_payload,
            capture_output=True, text=True, env=env, timeout=10,
        )
        return proc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_hook_silent_when_lf_only_stdout_matches_status_csv():
    """Baseline: LF-only output with STATUS.csv -> hook exits 0 silently.
    This case worked before the W9 fix too."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="coord/STATUS.csv\nspec/wave-9-plan.md\n",
        stdin_payload='{"tool_input": {"command": "git commit -m foo"}}',
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_hook_silent_when_crlf_stdout_matches_status_csv():
    """The W9 fix: CRLF-terminated output with STATUS.csv -> hook
    must exit 0 (not fire false-positive).  This was the bug."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="coord/STATUS.csv\r\nspec/wave-9-plan.md\r\n",
        stdin_payload='{"tool_input": {"command": "git commit -m foo"}}',
    )
    assert proc.returncode == 0, (
        f"Hook should exit 0 on CRLF output but exited "
        f"{proc.returncode}; stderr={proc.stderr[:200]}"
    )


def test_hook_fires_when_status_csv_not_touched():
    """Regression: a commit that genuinely doesn't touch STATUS.csv
    must still trigger the warning (exit 2)."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="src/harness/foo.py\ntests/test_foo.py\n",
        stdin_payload='{"tool_input": {"command": "git commit -m foo"}}',
    )
    assert proc.returncode == 2
    assert "STATUS.csv" in proc.stderr


def test_hook_fires_when_status_csv_not_touched_crlf():
    """Regression: CRLF output without STATUS.csv -> hook still fires."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="src/harness/foo.py\r\ntests/test_foo.py\r\n",
        stdin_payload='{"tool_input": {"command": "git commit -m foo"}}',
    )
    assert proc.returncode == 2
    assert "STATUS.csv" in proc.stderr


def test_hook_skips_when_command_is_not_git_commit():
    """The scope guard: hook should silently skip on non-git-commit invocations."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="anything",
        stdin_payload='{"tool_input": {"command": "ls -la"}}',
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_hook_skips_when_no_input():
    """No JSON payload -> hook should silently exit 0."""
    proc = _run_hook_with_fake_git(
        git_log_stdout="coord/STATUS.csv",
        stdin_payload="",
    )
    assert proc.returncode == 0
