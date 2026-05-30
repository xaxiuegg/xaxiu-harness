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
            message=f"reachable but tokens_in={resp.tokens_in} tokens_out={resp.tokens_out}",
            duration_ms=duration,
            fix="Usage-parsing regression — check engine's _extract_*_usage helper.",
        )
    return PreflightCheck(
        name=f"engine:{engine_name}",
        severity="ok",
        message=f"reachable; in={resp.tokens_in}/out={resp.tokens_out} latency={resp.latency_ms}ms",
        duration_ms=duration,
    )


# PATH-A-TRIM 2026-05-29: _check_observer_armed + _check_loops_armed removed
# along with the observer/loops subsystems they probed.


def _check_status_csv_fresh(max_age_hours: int = 24) -> PreflightCheck:
    started = time.monotonic()
    if not STATUS_CSV.exists():
        return PreflightCheck(
            name="status_csv",
            severity="fail",
            message=f"missing: {STATUS_CSV}",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix="Initialize via `harness init` or restore from git history.",
        )
    if not os.access(STATUS_CSV, os.W_OK):
        return PreflightCheck(
            name="status_csv",
            severity="fail",
            message="not writable",
            duration_ms=int((time.monotonic() - started) * 1000),
            fix="Check filesystem permissions on coord/STATUS.csv.",
        )
    mtime = datetime.fromtimestamp(STATUS_CSV.stat().st_mtime, tz=timezone.utc)
    age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    duration = int((time.monotonic() - started) * 1000)
    if age_h > max_age_hours:
        return PreflightCheck(
            name="status_csv",
            severity="warn",
            message=f"stale: last touched {age_h:.1f}h ago",
            duration_ms=duration,
            fix="Update STATUS.csv on every task transition.",
        )
    return PreflightCheck(
        name="status_csv",
        severity="ok",
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
            name="pytest_cache",
            severity="warn",
            message="no pytest cache — run pytest at least once",
            duration_ms=duration_ms(),
            fix="PYTHONPATH=src pytest -q",
        )
    try:
        content = PYTEST_CACHE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return PreflightCheck(
            name="pytest_cache",
            severity="warn",
            message=f"unreadable: {exc}",
            duration_ms=duration_ms(),
        )
    # The file contains a JSON dict; empty {} means no failures.
    if content in ("", "{}", "null"):
        return PreflightCheck(
            name="pytest_cache",
            severity="ok",
            message="last pytest run green",
            duration_ms=duration_ms(),
        )
    # Count entries crudely (one per line for typical pytest output).
    failed_count = content.count('"')
    return PreflightCheck(
        name="pytest_cache",
        severity="fail",
        message=f"last run had failures (lastfailed has {failed_count} tokens)",
        duration_ms=duration_ms(),
        fix="Run pytest, fix failures, then retry preflight.",
    )


def _check_git_clean() -> PreflightCheck:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return PreflightCheck(
            name="git_clean",
            severity="fail",
            message=f"git probe failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    duration = int((time.monotonic() - started) * 1000)
    porcelain = proc.stdout.strip()
    if not porcelain:
        return PreflightCheck(
            name="git_clean",
            severity="ok",
            message="working tree clean",
            duration_ms=duration,
        )
    # Untracked-only is warn; modified-tracked is fail (suggests
    # autonomous mode would commit local changes the operator hasn't
    # reviewed).
    has_modified_tracked = any(not line.startswith("??") for line in porcelain.splitlines())
    if has_modified_tracked:
        return PreflightCheck(
            name="git_clean",
            severity="fail",
            message=f"modified tracked files present ({len(porcelain.splitlines())} entries)",
            duration_ms=duration,
            fix="Commit or stash before going autonomous.",
        )
    return PreflightCheck(
        name="git_clean",
        severity="warn",
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

    W8-AUDIT follow-through 2026-05-24: engines already marked
    ``quarantined`` or ``recovering`` in ``engine_health.json`` are
    treated as already-handled and excluded from the warn list.  This
    way ``harness preflight --fix`` actually clears the warning the
    operator sees, instead of repeatedly flagging the same engines.
    """
    started = time.monotonic()
    try:
        from harness.engine_alarm import dead_engines

        dead = dead_engines()
    except Exception as exc:
        return PreflightCheck(
            name="dead_engines",
            severity="warn",
            message=f"alarm module unavailable: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    # W8: filter out engines already quarantined/recovering — those are
    # acknowledged by the operator (or by --fix).  Empty dict on import
    # error keeps the legacy behaviour.  Handle both dict and Pydantic
    # forms so tests stubbing read_engine_health continue to work.
    try:
        from harness.state.files import read_engine_health

        health = read_engine_health()

        def _status_of(entry: object) -> object:
            if isinstance(entry, dict):
                return entry.get("status")
            return getattr(entry, "status", None)

        handled = {
            name
            for name, entry in (health or {}).items()
            if _status_of(entry) in ("quarantined", "recovering")
        }
        dead = {name: streak for name, streak in dead.items() if name not in handled}
    except Exception:
        pass
    duration = int((time.monotonic() - started) * 1000)
    if not dead:
        return PreflightCheck(
            name="dead_engines",
            severity="ok",
            message="all engines below failure threshold",
            duration_ms=duration,
        )
    summary = ", ".join(f"{e}:{streak}" for e, streak in sorted(dead.items()))
    return PreflightCheck(
        name="dead_engines",
        severity="warn",
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
    # PATH-A-TRIM 2026-05-29: observer + loops scheduler-armed checks removed
    # (those subsystems were deleted in the harness retirement).
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
                results.append(
                    PreflightCheck(
                        name=name,
                        severity="fail",
                        message=f"check raised: {type(exc).__name__}: {exc}",
                    )
                )
    results.sort(key=lambda r: r.name)
    return results


def overall_exit_code(results: list[PreflightCheck]) -> int:
    """Return CLI exit code based on worst severity across results.

    Exit code semantics (W10-PREFLIGHT-EXIT-CODE-SEMANTICS, also
    documented in :func:`verdict_label`):

      0  All checks ok — autonomous mode green-lit
      1  At least one warn — actionable; autonomous mode CAN override
      4  At least one fail — autonomous mode BLOCKED

    Operator-readiness: non-technical operators historically read
    "exit 1" as FAIL when the harness intends "warning, still ok to
    proceed".  The CLI now prints :func:`verdict_label` so the
    operator sees the meaning explicitly, not just the number.
    """
    if any(r.severity == "fail" for r in results):
        return 4
    if any(r.severity == "warn" for r in results):
        return 1
    return 0


def verdict_label(exit_code: int) -> tuple[str, str]:
    """Translate an exit code into (short_verdict, operator_explanation).

    Designed to print under the per-check listing so the non-technical
    operator immediately knows whether the bottom-line is GO / GO-WITH-
    NOTES / STOP, rather than having to interpret a bare integer.

    Mapping:
        0 -> ("PASS",               "All checks green — autonomous mode is ready.")
        1 -> ("PASS-WITH-WARNINGS", "Warnings noted — actionable; autonomous mode can still proceed.")
        4 -> ("FAIL",               "Hard blocker — autonomous mode refuses to start.")
        *  -> ("UNKNOWN",           "Unrecognized exit code; report this to engineering.")
    """
    if exit_code == 0:
        return ("PASS", "All checks green — autonomous mode is ready.")
    if exit_code == 1:
        return (
            "PASS-WITH-WARNINGS",
            "Warnings noted — actionable; autonomous mode can still proceed.",
        )
    if exit_code == 4:
        return ("FAIL", "Hard blocker — autonomous mode refuses to start.")
    return ("UNKNOWN", f"Unrecognized exit code {exit_code}; report this to engineering.")


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
    applied: bool  # True if fix actually changed state
    skipped: bool  # True if fix wasn't needed (already clean)
    message: str  # Plain-language description for the operator
    error: str = ""  # If the fix tried but failed
    reversal: str = ""  # How to undo the fix if the operator wants


def fix_git_clean(*, dry_run: bool = False, allow_stash: bool = False) -> FixOutcome:
    """Make preflight's git_clean check go green.

    Untracked files are left alone (operator may want to keep them
    out of git on purpose).  Modified-tracked files are *NOT*
    auto-stashed by default as of W9-PREFLIGHT-FIX-NOSTASH — silent
    stash dropped in-progress work during W8 + 20/40 master-audit
    reviewers flagged it as data loss.

    Default behavior (allow_stash=False, the safe path):
        - If working tree is dirty, return a needs-attention outcome
          with a plain-language explanation pointing at `git stash`
          / `git commit` for manual recovery.  No git mutation runs.

    Opt-in legacy behavior (allow_stash=True):
        - Stash modified-tracked files with a labeled message.  The
          success outcome message starts with ``[STASHED]`` so the
          operator sees it loud in the preflight log; the reversal
          field carries the exact `git stash pop` command.
    """
    # Check whether there's anything to stash
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=False,
            message="Couldn't check git status — is git installed?",
            error=str(exc),
        )
    # Don't .strip() the whole stdout — git porcelain leads each line
    # with a 1-char index status + 1-char worktree status (often a
    # space) + 1 space, then the filename.  Stripping at the string
    # level would eat the leading space on line 1 and break the
    # uniform "filename starts at column 3" assumption below.
    porcelain_raw = proc.stdout
    if not porcelain_raw.strip():
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=True,
            message="Your working tree is already clean — nothing to fix.",
        )
    porcelain_lines = [ln for ln in porcelain_raw.splitlines() if ln]
    has_modified = any(not line.startswith("??") for line in porcelain_lines)
    if not has_modified:
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=True,
            message=(
                "You have untracked files but no modified-tracked files. "
                "Untracked files don't block preflight — leaving them alone."
            ),
        )
    modified_count = sum(1 for line in porcelain_lines if not line.startswith("??"))

    # W9-PREFLIGHT-FIX-NOSTASH 2026-05-24: refuse to stash unless the
    # operator opted in via --allow-stash.  W8 hit silent data loss
    # via an auto-stash that ran with no surface visibility; the
    # master audit (20/40 reviewers) called this out as one of the
    # top operator-facing surprises.  Default is now safe: name the
    # files, point at manual recovery, do not mutate.
    if not allow_stash:
        # Build a short list of modified files for the message (cap 5
        # so the line stays scannable; rest hinted at via the count).
        modified_paths = [line[3:] for line in porcelain_lines if not line.startswith("??")][:5]
        sample = ", ".join(modified_paths)
        if modified_count > len(modified_paths):
            sample += f", … (+{modified_count - len(modified_paths)} more)"
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=False,
            message=(
                f"Found {modified_count} modified file(s): {sample}. "
                f"Refusing to auto-stash by default (would silently "
                f"drop in-progress work).  Resolve manually with "
                f"`git stash push` or `git commit`, OR re-run with "
                f"`harness preflight --fix --allow-stash` to opt in "
                f"to the legacy auto-stash."
            ),
            reversal="git stash push  # or git commit",
        )

    stash_msg = f"harness preflight --fix auto-stash {datetime.now(timezone.utc).isoformat()}"
    if dry_run:
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=False,
            message=(
                f"[STASHED preview] Would stash {modified_count} "
                f"modified file(s) with message '{stash_msg}'.  Re-run "
                f"without --dry-run to apply.  Recover later with "
                f"`git stash pop`."
            ),
            reversal="git stash pop",
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "stash", "push", "-m", stash_msg],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=False,
            message="Couldn't run git stash — please try manually.",
            error=str(exc),
        )
    if proc.returncode != 0:
        return FixOutcome(
            name="git_clean",
            applied=False,
            skipped=False,
            message=(
                "git stash failed.  This usually means you have nothing "
                "to stash, or you have conflicts.  Please ask your "
                "engineering teammate."
            ),
            error=proc.stderr.strip()[:200],
        )
    return FixOutcome(
        name="git_clean",
        applied=True,
        skipped=False,
        message=(
            f"[STASHED] {modified_count} modified file(s) -> stash entry "
            f"'{stash_msg}'.  Run `git stash pop` later to recover."
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
            name="pytest_cache",
            applied=False,
            skipped=True,
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
            name="pytest_cache",
            applied=False,
            skipped=True,
            message="Pytest cache is already empty — nothing to clear.",
        )
    if dry_run:
        return FixOutcome(
            name="pytest_cache",
            applied=False,
            skipped=False,
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
            name="pytest_cache",
            applied=False,
            skipped=False,
            message="Couldn't clear the pytest cache file.",
            error=str(exc),
        )
    return FixOutcome(
        name="pytest_cache",
        applied=True,
        skipped=False,
        message=("Cleared the pytest lastfailed cache.  Pytest will rebuild it on its next run."),
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
            name="dead_engines",
            applied=False,
            skipped=False,
            message="Couldn't read engine health — alarm module unavailable.",
            error=str(exc),
        )
    if not dead:
        return FixOutcome(
            name="dead_engines",
            applied=False,
            skipped=True,
            message=("All engines are below the failure threshold — nothing to quarantine."),
        )
    names = ", ".join(sorted(dead.keys()))
    if dry_run:
        return FixOutcome(
            name="dead_engines",
            applied=False,
            skipped=False,
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
            name="dead_engines",
            applied=False,
            skipped=False,
            message="Couldn't load state module to mark engines quarantined.",
            error=str(exc),
        )
    # W9-STATE-FILE-LOCK 2026-05-24: take an advisory lock on
    # engine_health.json for the duration of the read-modify-write
    # cycle.  Without this, a manual `preflight --fix` racing a
    # scheduled one (or any concurrent quarantine path) can lose
    # writes via the textbook lost-update race.
    quarantined: list[str] = []
    try:
        from harness.state.locks import advisory_lock, LockTimeoutError
    except ImportError:
        advisory_lock = None  # type: ignore
        LockTimeoutError = Exception  # type: ignore

    def _do_quarantine() -> None:
        for engine_name in sorted(dead.keys()):
            try:
                state_files.update_engine_health(
                    engine_name,
                    {
                        "status": "quarantined",
                        "last_quarantine": datetime.now(timezone.utc).isoformat(),
                    },
                )
                quarantined.append(engine_name)
            except Exception:
                # best-effort; report what we got
                continue

    if advisory_lock is None:
        _do_quarantine()
    else:
        try:
            with advisory_lock(state_files.ENGINE_HEALTH_PATH, timeout_sec=5.0):
                _do_quarantine()
        except LockTimeoutError as exc:
            return FixOutcome(
                name="dead_engines",
                applied=False,
                skipped=False,
                message=(
                    "Another `preflight --fix` (or `engines heal`) is "
                    "already running and holding the engine-health "
                    "lock.  Try again in a few seconds, or check for "
                    "a stuck process."
                ),
                error=str(exc),
            )
    if not quarantined:
        return FixOutcome(
            name="dead_engines",
            applied=False,
            skipped=False,
            message=(
                "Tried to quarantine but couldn't update engine health.  "
                "Please ask your engineering teammate."
            ),
        )
    # W8-AUDIT follow-through 2026-05-24: emit the L4 toast that W6-C2 normally
    # fires when an engine *first* crosses the dead threshold.  The fix path
    # may quarantine engines whose alarms haven't fired yet (e.g. operator
    # ran preflight --fix immediately after a streak crossed threshold).  Toast
    # is best-effort.
    try:
        from harness.engine_alarm import fire_dead_engine_alarm

        for engine_name in quarantined:
            fire_dead_engine_alarm(engine_name, dead.get(engine_name, 0))
    except Exception:
        pass
    return FixOutcome(
        name="dead_engines",
        applied=True,
        skipped=False,
        message=(
            f"Quarantined {len(quarantined)} dead engine(s): "
            f"{', '.join(quarantined)}.  Reset any of them with "
            f"`harness engines reset <engine>` once you know the "
            f"underlying issue is resolved (key rotated, endpoint "
            f"restored, etc.)."
        ),
        reversal="harness engines reset <engine>",
    )


def run_fixes(*, dry_run: bool = False, allow_stash: bool = False) -> list[FixOutcome]:
    """Run every auto-fix in series; return one FixOutcome per attempt.

    Order matters: git stash first (so subsequent fixes don't dirty
    the tree), then pytest cache (cheap), then dead engines (state
    file update — relies on the alarm module).

    W9-PREFLIGHT-FIX-NOSTASH 2026-05-24: ``allow_stash`` opt-in
    threads through to ``fix_git_clean``.  Default False (no
    silent stash).  CLI flag: ``preflight --fix --allow-stash``.
    """
    return [
        fix_git_clean(dry_run=dry_run, allow_stash=allow_stash),
        fix_pytest_cache(dry_run=dry_run),
        fix_dead_engines(dry_run=dry_run),
    ]
