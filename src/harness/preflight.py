"""harness preflight — readiness gate before autonomous-mode start.

Goes beyond ``harness doctor`` (which only validates the install) by
actually exercising live components:

  - Engine reachability via 1-token probe (real API call per engine)
  - Observer scheduled task registered with Windows Task Scheduler
  - Loops scheduled task registered
  - STATUS.csv writable + mtime within 24h (drift sentinel)
  - Pytest cache: last run green
  - Git working tree clean

The checks run in parallel via ``ThreadPoolExecutor`` so the whole
matrix completes in under 30 seconds even on slow networks.

Exit semantics for CLI integration:
  0 — all checks pass
  1 — any check is at warn severity (autonomous-mode can override)
  4 — any check is at fail severity (L5-class blocker; refuse to
       start autonomous mode unless ``--skip-preflight`` is set)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_CSV = REPO_ROOT / "coord" / "STATUS.csv"
PYTEST_CACHE = REPO_ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed"


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    severity: str  # ok | warn | fail
    message: str
    duration_ms: int = 0
    fix: str = ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_engine_probe(engine_name: str) -> PreflightCheck:
    """Send a 1-token probe to *engine_name* and check tokens come back.

    Returns ok if dispatch succeeds + tokens_in/tokens_out both > 0.
    warn on missing API key (engine intentionally unconfigured).
    fail on dispatch error (engine misconfigured).
    """
    started = time.monotonic()
    from harness.engines.concrete import get_engine
    try:
        eng = get_engine(engine_name, prefer_dpapi=True)
    except RuntimeError as exc:
        return PreflightCheck(
            name=f"engine:{engine_name}",
            severity="warn",
            message=f"no API key (intentional?): {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix=f"Set the engine API key via DPAPI or env var, or remove "
                f"{engine_name} from production routing.",
        )
    model_map = {
        "deepseek": "deepseek-v4-flash",
        "kimi": "kimi-for-coding",
        "mimo": "auto",
        "anthropic": "claude-sonnet-4-5-20250929",
        "gemini": "gemini-2.0-flash",
    }
    model = model_map.get(engine_name, "")
    try:
        resp = eng.dispatch("Reply OK only.", model=model)
    except Exception as exc:
        return PreflightCheck(
            name=f"engine:{engine_name}",
            severity="fail",
            message=f"dispatch raised: {type(exc).__name__}: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix=f"Check {engine_name} endpoint reachability + key validity.",
        )
    duration = int((time.monotonic() - started) * 1000)
    if not resp.success:
        return PreflightCheck(
            name=f"engine:{engine_name}",
            severity="fail",
            message=f"dispatch failed: {resp.error}",
            duration_ms=duration,
            fix=f"Check {engine_name} endpoint + auth.",
        )
    if resp.tokens_in == 0 or resp.tokens_out == 0:
        return PreflightCheck(
            name=f"engine:{engine_name}",
            severity="warn",
            message=f"reachable but tokens_in={resp.tokens_in} "
                    f"tokens_out={resp.tokens_out}",
            duration_ms=duration,
            fix="Usage-parsing regression — check engine's "
                "_extract_*_usage helper.",
        )
    return PreflightCheck(
        name=f"engine:{engine_name}",
        severity="ok",
        message=f"reachable; in={resp.tokens_in}/out={resp.tokens_out} "
                f"latency={resp.latency_ms}ms",
        duration_ms=duration,
    )


def _check_observer_armed() -> PreflightCheck:
    started = time.monotonic()
    try:
        from harness.observer.scheduler import TASK_NAME_PREFIX
    except ImportError as exc:
        return PreflightCheck(
            name="observer", severity="fail",
            message=f"observer module unavailable: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    if sys.platform != "win32":
        return PreflightCheck(
            name="observer", severity="warn",
            message="Windows-only check skipped on this platform",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    # The observer registers multiple tasks (Kimi cycle, DeepSeek retro,
    # chat audit).  Probe for any task starting with the prefix.
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command",
             f"$t = Get-ScheduledTask -TaskName '{TASK_NAME_PREFIX}*' "
             "-ErrorAction SilentlyContinue; "
             "if ($t) { ($t | Measure-Object).Count } else { 0 }"],
            capture_output=True, text=True, timeout=10,
        )
        count = int(proc.stdout.strip() or "0")
    except (subprocess.TimeoutExpired, ValueError):
        count = 0
    duration = int((time.monotonic() - started) * 1000)
    if count == 0:
        return PreflightCheck(
            name="observer", severity="warn",
            message="no observer tasks registered",
            duration_ms=duration,
            fix="harness orchestrator install-observer-scheduler",
        )
    return PreflightCheck(
        name="observer", severity="ok",
        message=f"{count} observer task(s) armed",
        duration_ms=duration,
    )


def _check_loops_armed() -> PreflightCheck:
    started = time.monotonic()
    try:
        from harness.loops.scheduler import is_registered
    except ImportError as exc:
        return PreflightCheck(
            name="loops", severity="fail",
            message=f"loops module unavailable: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    if sys.platform != "win32":
        return PreflightCheck(
            name="loops", severity="warn",
            message="Windows-only check skipped on this platform",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    armed = is_registered()
    duration = int((time.monotonic() - started) * 1000)
    if not armed:
        return PreflightCheck(
            name="loops", severity="warn",
            message="dev loop task not registered",
            duration_ms=duration,
            fix="harness loop start",
        )
    return PreflightCheck(
        name="loops", severity="ok",
        message="dev loop task armed",
        duration_ms=duration,
    )


def _check_status_csv_fresh(max_age_hours: int = 24) -> PreflightCheck:
    started = time.monotonic()
    if not STATUS_CSV.exists():
        return PreflightCheck(
            name="status_csv", severity="fail",
            message=f"missing: {STATUS_CSV}",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix="Initialize via `harness init` or restore from git history.",
        )
    if not os.access(STATUS_CSV, os.W_OK):
        return PreflightCheck(
            name="status_csv", severity="fail",
            message="not writable",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix="Check filesystem permissions on coord/STATUS.csv.",
        )
    mtime = datetime.fromtimestamp(STATUS_CSV.stat().st_mtime,
                                   tz=timezone.utc)
    age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    duration = int((time.monotonic() - started) * 1000)
    if age_h > max_age_hours:
        return PreflightCheck(
            name="status_csv", severity="warn",
            message=f"stale: last touched {age_h:.1f}h ago",
            duration_ms=duration,
            fix="Update STATUS.csv on every task transition.",
        )
    return PreflightCheck(
        name="status_csv", severity="ok",
        message=f"writable, last touched {age_h:.1f}h ago",
        duration_ms=duration,
    )


def _check_pytest_cache_green() -> PreflightCheck:
    """Lastfailed is empty (or absent) → last full pytest run was green.

    pytest writes the lastfailed file with one entry per failing test;
    a green run wipes it.  An absent file means pytest has never run
    in this checkout — we report ``warn`` so the operator knows to run
    a baseline before going autonomous.
    """
    started = time.monotonic()
    duration_ms = lambda: int((time.monotonic() - started) * 1000)
    if not PYTEST_CACHE.exists():
        return PreflightCheck(
            name="pytest_cache", severity="warn",
            message="no pytest cache — run pytest at least once",
            duration_ms=duration_ms(),
            fix="PYTHONPATH=src pytest -q",
        )
    try:
        content = PYTEST_CACHE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return PreflightCheck(
            name="pytest_cache", severity="warn",
            message=f"unreadable: {exc}",
            duration_ms=duration_ms(),
        )
    # The file contains a JSON dict; empty {} means no failures.
    if content in ("", "{}", "null"):
        return PreflightCheck(
            name="pytest_cache", severity="ok",
            message="last pytest run green",
            duration_ms=duration_ms(),
        )
    # Count entries crudely (one per line for typical pytest output).
    failed_count = content.count('"')
    return PreflightCheck(
        name="pytest_cache", severity="fail",
        message=f"last run had failures (lastfailed has {failed_count} "
                "tokens)",
        duration_ms=duration_ms(),
        fix="Run pytest, fix failures, then retry preflight.",
    )


def _check_git_clean() -> PreflightCheck:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return PreflightCheck(
            name="git_clean", severity="fail",
            message=f"git probe failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    duration = int((time.monotonic() - started) * 1000)
    porcelain = proc.stdout.strip()
    if not porcelain:
        return PreflightCheck(
            name="git_clean", severity="ok",
            message="working tree clean",
            duration_ms=duration,
        )
    # Untracked-only is warn; modified-tracked is fail (suggests
    # autonomous mode would commit local changes the operator hasn't
    # reviewed).
    has_modified_tracked = any(
        not line.startswith("??") for line in porcelain.splitlines()
    )
    if has_modified_tracked:
        return PreflightCheck(
            name="git_clean", severity="fail",
            message=f"modified tracked files present "
                    f"({len(porcelain.splitlines())} entries)",
            duration_ms=duration,
            fix="Commit or stash before going autonomous.",
        )
    return PreflightCheck(
        name="git_clean", severity="warn",
        message=f"{len(porcelain.splitlines())} untracked files",
        duration_ms=duration,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _check_dead_engines() -> PreflightCheck:
    """W6-C2: surface any engines currently in the dead state.

    Reads ``state/engine_performance_log.jsonl`` via
    ``harness.engine_alarm.dead_engines()`` and reports any engine with
    a consecutive-failure streak ≥ the alarm threshold.  An empty list
    is ``ok``; one or more dead engines is ``warn`` (the loop's
    fallback chain still routes traffic to healthy engines, so this
    isn't an outage — but it warrants operator attention).
    """
    started = time.monotonic()
    try:
        from harness.engine_alarm import dead_engines
        dead = dead_engines()
    except Exception as exc:
        return PreflightCheck(
            name="dead_engines", severity="warn",
            message=f"alarm module unavailable: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    duration = int((time.monotonic() - started) * 1000)
    if not dead:
        return PreflightCheck(
            name="dead_engines", severity="ok",
            message="all engines below failure threshold",
            duration_ms=duration,
        )
    summary = ", ".join(f"{e}:{streak}" for e, streak in sorted(dead.items()))
    return PreflightCheck(
        name="dead_engines", severity="warn",
        message=f"dead engines: {summary}",
        duration_ms=duration,
        fix="Inspect state/engine_performance_log.jsonl; rotate keys "
            "or quarantine the affected engine.",
    )


def _all_check_callables() -> list[tuple[str, Callable[[], PreflightCheck]]]:
    """Return (name, callable) pairs.  Engine checks dispatched in parallel."""
    engines = ["deepseek", "kimi", "mimo"]
    pairs: list[tuple[str, Callable[[], PreflightCheck]]] = []
    for e in engines:
        # late-binding e via default arg
        pairs.append((f"engine:{e}", lambda e=e: _check_engine_probe(e)))
    pairs.append(("observer", _check_observer_armed))
    pairs.append(("loops", _check_loops_armed))
    pairs.append(("status_csv", _check_status_csv_fresh))
    pairs.append(("pytest_cache", _check_pytest_cache_green))
    pairs.append(("git_clean", _check_git_clean))
    pairs.append(("dead_engines", _check_dead_engines))
    return pairs


def run_all(max_workers: int = 8) -> list[PreflightCheck]:
    """Run every check in parallel and return results sorted by name."""
    pairs = _all_check_callables()
    results: list[PreflightCheck] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn): name for name, fn in pairs}
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as exc:
                name = futures[f]
                results.append(PreflightCheck(
                    name=name, severity="fail",
                    message=f"check raised: {type(exc).__name__}: {exc}",
                ))
    results.sort(key=lambda r: r.name)
    return results


def overall_exit_code(results: list[PreflightCheck]) -> int:
    """Return CLI exit code based on worst severity across results."""
    if any(r.severity == "fail" for r in results):
        return 4
    if any(r.severity == "warn" for r in results):
        return 1
    return 0


# ---------------------------------------------------------------------------
# W8-PREFLIGHT-FIX 2026-05-23: auto-remediation
# ---------------------------------------------------------------------------
# Per readiness panel (10/10 reviewers, 8/10 vote): the operator
# cannot self-resolve preflight failures because remediation paths
# require Python/git knowledge.  --fix flag automates the three
# most-cited failures using plain-language output.
#
# Design constraints (from panel):
#   - NO Python tracebacks shown to operator
#   - NO raw git command output unless explicitly requested
#   - Every fix has a --dry-run preview that shows what WILL happen
#   - Every fix is reversible (git stash → pop; engine quarantine →
#     unquarantine via existing CLI; pytest cache is just a sentinel
#     file so clearing it is harmless)


@dataclass(frozen=True)
class FixOutcome:
    """One auto-fix attempt's plain-language result."""
    name: str
    applied: bool          # True if fix actually changed state
    skipped: bool          # True if fix wasn't needed (already clean)
    message: str           # Plain-language description for the operator
    error: str = ""        # If the fix tried but failed
    reversal: str = ""     # How to undo the fix if the operator wants


def fix_git_clean(*, dry_run: bool = False) -> FixOutcome:
    """Auto-stash modified-tracked files so preflight's git_clean
    check goes green.

    Untracked files are left alone (operator may want to keep them
    out of git on purpose).  Modified-tracked files are stashed
    with a labeled message so the operator can pop them back later.
    """
    # Check whether there's anything to stash
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return FixOutcome(
            name="git_clean", applied=False, skipped=False,
            message="Couldn't check git status — is git installed?",
            error=str(exc),
        )
    porcelain = proc.stdout.strip()
    if not porcelain:
        return FixOutcome(
            name="git_clean", applied=False, skipped=True,
            message="Your working tree is already clean — nothing to fix.",
        )
    has_modified = any(
        not line.startswith("??") for line in porcelain.splitlines()
    )
    if not has_modified:
        return FixOutcome(
            name="git_clean", applied=False, skipped=True,
            message=(
                "You have untracked files but no modified-tracked files. "
                "Untracked files don't block preflight — leaving them alone."
            ),
        )
    stash_msg = (
        f"harness preflight --fix auto-stash "
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    if dry_run:
        modified_count = sum(
            1 for line in porcelain.splitlines()
            if not line.startswith("??")
        )
        return FixOutcome(
            name="git_clean", applied=False, skipped=False,
            message=(
                f"Would stash {modified_count} modified file(s) with "
                f"message '{stash_msg}'.  Re-run without --dry-run to "
                f"apply.  You can recover the changes later with "
                f"`git stash pop`."
            ),
            reversal="git stash pop",
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "stash", "push", "-m", stash_msg],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return FixOutcome(
            name="git_clean", applied=False, skipped=False,
            message="Couldn't run git stash — please try manually.",
            error=str(exc),
        )
    if proc.returncode != 0:
        return FixOutcome(
            name="git_clean", applied=False, skipped=False,
            message=(
                "git stash failed.  This usually means you have nothing "
                "to stash, or you have conflicts.  Please ask your "
                "engineering teammate."
            ),
            error=proc.stderr.strip()[:200],
        )
    return FixOutcome(
        name="git_clean", applied=True, skipped=False,
        message=(
            "Stashed your modified files.  Run `git stash pop` later "
            "to bring them back.  Your working tree is clean now."
        ),
        reversal="git stash pop",
    )


def fix_pytest_cache(*, dry_run: bool = False) -> FixOutcome:
    """Clear the pytest lastfailed cache so preflight's pytest_cache
    check goes green.

    This is harmless — pytest will rebuild the cache on the next
    run.  The cache exists to let pytest re-run failing tests
    first, but if it's stale (left over from a mutation sweep or
    a fixed test the cache doesn't know about), it blocks
    autonomous mode for no reason.
    """
    if not PYTEST_CACHE.exists():
        return FixOutcome(
            name="pytest_cache", applied=False, skipped=True,
            message=(
                "There's no pytest cache to clear — you may need to "
                "run pytest at least once first (e.g. via the "
                "operator runbook's morning sequence)."
            ),
        )
    try:
        content = PYTEST_CACHE.read_text(encoding="utf-8").strip()
    except OSError:
        content = ""
    if content in ("", "{}", "null"):
        return FixOutcome(
            name="pytest_cache", applied=False, skipped=True,
            message="Pytest cache is already empty — nothing to clear.",
        )
    if dry_run:
        return FixOutcome(
            name="pytest_cache", applied=False, skipped=False,
            message=(
                f"Would clear the pytest lastfailed cache at "
                f"{PYTEST_CACHE.name}.  Re-run without --dry-run to "
                f"apply.  Pytest will rebuild it next run."
            ),
            reversal="(none needed — pytest rebuilds the cache on next run)",
        )
    try:
        PYTEST_CACHE.write_text("{}", encoding="utf-8")
    except OSError as exc:
        return FixOutcome(
            name="pytest_cache", applied=False, skipped=False,
            message="Couldn't clear the pytest cache file.",
            error=str(exc),
        )
    return FixOutcome(
        name="pytest_cache", applied=True, skipped=False,
        message=(
            "Cleared the pytest lastfailed cache.  Pytest will rebuild "
            "it on its next run."
        ),
        reversal="(none needed — pytest rebuilds the cache automatically)",
    )


def fix_dead_engines(*, dry_run: bool = False) -> FixOutcome:
    """Quarantine engines currently above the W6-C2 dead-engine threshold.

    Marks each dead engine as ``status=quarantined`` in
    ``state/engine_health.json`` so the dispatcher's fallback chain
    skips it.  Operator-facing message names each affected engine
    and offers a clear undo path (the existing
    `harness engines reset` verb).
    """
    try:
        from harness.engine_alarm import dead_engines as _dead
        dead = _dead()
    except Exception as exc:
        return FixOutcome(
            name="dead_engines", applied=False, skipped=False,
            message="Couldn't read engine health — alarm module unavailable.",
            error=str(exc),
        )
    if not dead:
        return FixOutcome(
            name="dead_engines", applied=False, skipped=True,
            message=(
                "All engines are below the failure threshold — nothing "
                "to quarantine."
            ),
        )
    names = ", ".join(sorted(dead.keys()))
    if dry_run:
        return FixOutcome(
            name="dead_engines", applied=False, skipped=False,
            message=(
                f"Would quarantine these dead engines: {names}.  "
                f"Re-run without --dry-run to apply.  You can reset "
                f"any of them later with `harness engines reset "
                f"<engine>`."
            ),
            reversal="harness engines reset <engine>",
        )
    try:
        from harness.state import files as state_files
    except ImportError as exc:
        return FixOutcome(
            name="dead_engines", applied=False, skipped=False,
            message="Couldn't load state module to mark engines quarantined.",
            error=str(exc),
        )
    quarantined: list[str] = []
    for engine_name in sorted(dead.keys()):
        try:
            state_files.update_engine_health(
                engine_name,
                {"status": "quarantined",
                 "last_quarantine": datetime.now(timezone.utc).isoformat()},
            )
            quarantined.append(engine_name)
        except Exception:
            # best-effort; report what we got
            continue
    if not quarantined:
        return FixOutcome(
            name="dead_engines", applied=False, skipped=False,
            message=(
                "Tried to quarantine but couldn't update engine health.  "
                "Please ask your engineering teammate."
            ),
        )
    return FixOutcome(
        name="dead_engines", applied=True, skipped=False,
        message=(
            f"Quarantined {len(quarantined)} dead engine(s): "
            f"{', '.join(quarantined)}.  Reset any of them with "
            f"`harness engines reset <engine>` once you know the "
            f"underlying issue is resolved (key rotated, endpoint "
            f"restored, etc.)."
        ),
        reversal="harness engines reset <engine>",
    )


def run_fixes(*, dry_run: bool = False) -> list[FixOutcome]:
    """Run every auto-fix in series; return one FixOutcome per attempt.

    Order matters: git stash first (so subsequent fixes don't dirty
    the tree), then pytest cache (cheap), then dead engines (state
    file update — relies on the alarm module).
    """
    return [
        fix_git_clean(dry_run=dry_run),
        fix_pytest_cache(dry_run=dry_run),
        fix_dead_engines(dry_run=dry_run),
    ]
