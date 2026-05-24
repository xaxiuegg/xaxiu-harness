"""W9-PREFLIGHT-FIX-NOSTASH: regression tests for the no-silent-stash
default + --allow-stash opt-in.

The W8 wave shipped `preflight --fix` with auto-stash hard-wired on,
and silently dropped in-progress work; 20/40 master-audit reviewers
flagged it as one of the top operator-facing surprises.  Wave 9
inverts the default: dirty tree => name files + point at manual
recovery; --allow-stash opts in to the legacy behavior with a loud
[STASHED] message.

These tests use `subprocess.run` monkey-patching so the real `git
stash` is never invoked from CI.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from harness import preflight


# -- helpers ---------------------------------------------------------------


def _fake_status(porcelain_lines: list[str]):
    """Build a SimpleNamespace mimicking subprocess.run for `git status --porcelain`."""
    return SimpleNamespace(
        stdout="\n".join(porcelain_lines),
        stderr="",
        returncode=0,
    )


def _fake_stash_success():
    return SimpleNamespace(stdout="Saved working directory", stderr="", returncode=0)


def _stub_subprocess_run(monkeypatch, *, status_lines: list[str],
                         stash_result=None):
    """Stub subprocess.run for the two git invocations fix_git_clean makes.

    Returns a list-of-call-args spy so tests can assert which git
    commands ran.
    """
    spy: list[list[str]] = []

    def _fake_run(args, **kw):
        spy.append(list(args))
        # First call is always `git status --porcelain`
        if "status" in args:
            return _fake_status(status_lines)
        if "stash" in args and "push" in args:
            return stash_result or _fake_stash_success()
        # Fallback
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(preflight.subprocess, "run", _fake_run)
    return spy


# -- Clean tree -----------------------------------------------------------


def test_clean_tree_skips_with_or_without_allow_stash(monkeypatch):
    """Clean working tree -> skipped, regardless of --allow-stash."""
    spy = _stub_subprocess_run(monkeypatch, status_lines=[])
    out = preflight.fix_git_clean(dry_run=False, allow_stash=False)
    assert out.skipped is True
    assert out.applied is False
    assert "already clean" in out.message.lower()
    # No stash invocation
    assert all("stash" not in args for args in spy)

    spy2 = _stub_subprocess_run(monkeypatch, status_lines=[])
    out2 = preflight.fix_git_clean(dry_run=False, allow_stash=True)
    assert out2.skipped is True
    assert all("stash" not in args for args in spy2)


def test_only_untracked_files_skips(monkeypatch):
    """Untracked files alone (no modified-tracked) skips with no stash."""
    spy = _stub_subprocess_run(monkeypatch,
                                status_lines=["?? new_file.txt"])
    out = preflight.fix_git_clean(dry_run=False, allow_stash=False)
    assert out.skipped is True
    assert "untracked" in out.message.lower()
    assert all("stash" not in args for args in spy)


# -- Dirty tree, default (no --allow-stash) -------------------------------


def test_dirty_tree_default_refuses_to_stash(monkeypatch):
    """The load-bearing W9 behavior: dirty tree + default => no stash."""
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py", " M src/harness/bar.py"],
    )
    out = preflight.fix_git_clean(dry_run=False, allow_stash=False)
    assert out.applied is False
    assert out.skipped is False
    assert "refusing" in out.message.lower() or "won't auto-stash" in out.message.lower() or "refuse" in out.message.lower()
    # Names the files
    assert "src/harness/foo.py" in out.message
    assert "src/harness/bar.py" in out.message
    # Points at the opt-in flag
    assert "--allow-stash" in out.message
    # Reversal hints at manual paths, not auto-stash pop
    assert "stash push" in out.reversal or "commit" in out.reversal
    # CRITICAL: git stash was never invoked
    assert all(not ("stash" in args and "push" in args) for args in spy)


def test_dirty_tree_default_truncates_file_list(monkeypatch):
    """Many modified files: list is capped + 'X more' hint shown."""
    files = [f"src/harness/file_{i}.py" for i in range(10)]
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[f" M {f}" for f in files],
    )
    out = preflight.fix_git_clean(dry_run=False, allow_stash=False)
    assert out.applied is False
    # First 5 shown
    for f in files[:5]:
        assert f in out.message
    # "X more" overflow hint
    assert "(+5 more)" in out.message
    assert all(not ("stash" in args and "push" in args) for args in spy)


# -- Dirty tree, --allow-stash opt-in -------------------------------------


def test_dirty_tree_allow_stash_actually_stashes(monkeypatch):
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py"],
        stash_result=_fake_stash_success(),
    )
    out = preflight.fix_git_clean(dry_run=False, allow_stash=True)
    assert out.applied is True
    assert "[STASHED]" in out.message
    assert out.reversal == "git stash pop"
    # Stash WAS invoked
    assert any("stash" in args and "push" in args for args in spy)


def test_dirty_tree_allow_stash_dry_run_does_not_stash(monkeypatch):
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py"],
    )
    out = preflight.fix_git_clean(dry_run=True, allow_stash=True)
    assert out.applied is False
    assert out.skipped is False
    assert "[STASHED preview]" in out.message
    assert "1" in out.message  # modified count surfaced
    # Stash NOT invoked under dry-run
    assert all(not ("stash" in args and "push" in args) for args in spy)


def test_dirty_tree_allow_stash_handles_stash_failure(monkeypatch):
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py"],
        stash_result=SimpleNamespace(
            stdout="", stderr="conflict on commit",
            returncode=1,
        ),
    )
    out = preflight.fix_git_clean(dry_run=False, allow_stash=True)
    assert out.applied is False
    assert "stash failed" in out.message.lower()
    assert "conflict on commit" in out.error


# -- run_fixes threads allow_stash through -------------------------------


def test_run_fixes_default_does_not_stash(monkeypatch):
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py"],
    )
    # Stub the other two fixers so we only exercise git_clean path
    monkeypatch.setattr(preflight, "fix_pytest_cache",
                        lambda dry_run=False: preflight.FixOutcome(
                            name="pytest_cache", applied=False, skipped=True,
                            message="ok"))
    monkeypatch.setattr(preflight, "fix_dead_engines",
                        lambda dry_run=False: preflight.FixOutcome(
                            name="dead_engines", applied=False, skipped=True,
                            message="ok"))

    outcomes = preflight.run_fixes(dry_run=False)  # allow_stash=False default
    git_clean = next(o for o in outcomes if o.name == "git_clean")
    assert git_clean.applied is False
    assert "--allow-stash" in git_clean.message
    # Critical: stash never invoked
    assert all(not ("stash" in args and "push" in args) for args in spy)


def test_run_fixes_allow_stash_invokes_stash(monkeypatch):
    spy = _stub_subprocess_run(
        monkeypatch,
        status_lines=[" M src/harness/foo.py"],
    )
    monkeypatch.setattr(preflight, "fix_pytest_cache",
                        lambda dry_run=False: preflight.FixOutcome(
                            name="pytest_cache", applied=False, skipped=True,
                            message="ok"))
    monkeypatch.setattr(preflight, "fix_dead_engines",
                        lambda dry_run=False: preflight.FixOutcome(
                            name="dead_engines", applied=False, skipped=True,
                            message="ok"))

    outcomes = preflight.run_fixes(dry_run=False, allow_stash=True)
    git_clean = next(o for o in outcomes if o.name == "git_clean")
    assert git_clean.applied is True
    assert "[STASHED]" in git_clean.message
    assert any("stash" in args and "push" in args for args in spy)
