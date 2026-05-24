"""W9-MUTATION-CANARY — 3-mutant rolling spot-check.

Deferred from W8 Track A.  Now load-bearing per the master audit:
the MiMo gate flips PASS↔STOP under noise, so we need a
DETERMINISTIC regression signal that bypasses MiMo entirely.

Strategy:
  - Pick one module per run from the rotation (proxy → observer →
    loops → dashboard → engines → …).
  - Apply 3 single-line mutations.
  - For each mutation, run pytest with ``-x`` (stop on first
    failure) — the canary only needs to know "did at least one test
    catch this mutation?", not the full failure count.
  - If a mutation survives (zero failures), surface as a regression
    signal (exit 1 + flag a follow-up STATUS row).

Rotation state in ``coord/canary_state.json``:
    {"next_module": "src/harness/observer/hook.py"}

Wall-clock target: <3 min per run (3 × ~50s pytest -x = ~150s).

Usage:
    PYTHONPATH=src python -X utf8 scripts/run_mutation_canary.py
    PYTHONPATH=src python -X utf8 scripts/run_mutation_canary.py --module src/harness/proxy/dispatcher.py
    PYTHONPATH=src python -X utf8 scripts/run_mutation_canary.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "coord" / "canary_state.json"
REPORT_DIR = REPO_ROOT / "coord" / "reviews"

# Rotation order: under-tested modules first (per master audit M07
# and M13 PROXY-SAFETY).  These are the modules NOT covered by the
# W6-A3 hot-5 sweep, sorted by load-bearing risk (circuit breaker
# first, then observer cycle, then the rest).
ROTATION: list[str] = [
    "src/harness/proxy/circuit.py",
    "src/harness/observer/cycle.py",
    "src/harness/loops/runner.py",
    "src/harness/dashboard/app.py",
    "src/harness/engines/concrete.py",
]

# Same mutation template as run_mutation_sweep.py; deterministic str-
# replace single-shot.  A mutation that doesn't match the source
# (pattern absent) is "skipped" and not counted.
MUTATIONS: list[tuple[str, str, str]] = [
    ("bool_return_flip",       "return True",   "return False"),
    ("eq_to_neq",              " == ",          " != "),
    ("gt_to_ge",               " > 0",          " >= 0"),
    ("is_not_none_to_is_none", "is not None",   "is None"),
    ("plus1_to_minus1",        " + 1",          " - 1"),
    # W11-MUTATION-PATTERN-EXPANSION 2026-05-25: async-aware + common-
    # idiom patterns so modules without int/bool flips still get meaningful
    # canary coverage.  observer/cycle.py was 0/3 in W10-FRESH-CANARY-
    # MODULES because none of the original 5 patterns matched its idioms;
    # the patterns below catch the parse-and-return idioms it (and many
    # other modules) use.
    ("await_call_strip",       "await ",        ""),
    ("async_to_sync_def",      "async def ",    "def "),
    ("return_empty_list_to_none", "return []",  "return None"),
    ("isinstance_negate",      "isinstance(",   "not isinstance("),
]

# Canary picks the FIRST CANARY_MUTATION_COUNT patterns from this list per
# run.  To prioritize async patterns on async modules, override via
# --pattern on the CLI (future polish).

# How many mutations to apply per canary run (vs sweep's 5).
CANARY_MUTATION_COUNT = 3

# pytest -x timeout — single mutant run.
PYTEST_TIMEOUT_SEC = 180


@dataclass
class CanaryResult:
    module: str
    label: str
    pattern: str
    applied: bool
    killed: bool       # at least one test failed (= mutation caught)
    failed_tests: int  # 1 if -x stopped on first failure; 0 if all passed
    duration_s: float
    skipped_reason: str | None = None  # set when applied=False


@dataclass
class CanaryRun:
    """Aggregate of a single canary run on one module."""
    module: str
    started_at: str
    results: list[CanaryResult] = field(default_factory=list)
    total_duration_s: float = 0.0
    next_module: str | None = None  # rotation pointer for state.json

    @property
    def applied_count(self) -> int:
        return sum(1 for r in self.results if r.applied)

    @property
    def killed_count(self) -> int:
        return sum(1 for r in self.results if r.killed)

    @property
    def all_killed(self) -> bool:
        """True iff every applied mutation was killed.

        An applied count of 0 is treated as NEUTRAL (no signal) — the
        canary returns success because nothing escaped, but the report
        flags the module as "no mutations applied this run".
        """
        applied = [r for r in self.results if r.applied]
        if not applied:
            return True
        return all(r.killed for r in applied)


# -- Rotation state --------------------------------------------------------


def load_rotation_state() -> str:
    """Return the next module to test.  Bootstraps state.json if absent."""
    if not STATE_PATH.exists():
        return ROTATION[0]
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        nxt = data.get("next_module")
        if nxt in ROTATION:
            return nxt
    except (OSError, json.JSONDecodeError):
        pass
    return ROTATION[0]


def advance_rotation(current: str) -> str:
    """Return the module that follows *current* in ROTATION."""
    try:
        idx = ROTATION.index(current)
    except ValueError:
        return ROTATION[0]
    return ROTATION[(idx + 1) % len(ROTATION)]


def save_rotation_state(next_module: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"next_module": next_module, "updated_at":
                    datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


# -- Mutation application --------------------------------------------------


def apply_mutation(module_path: Path, search: str, replace: str) -> tuple[bool, str]:
    """Return (applied, original_text).  applied=False if pattern absent."""
    original = module_path.read_text(encoding="utf-8")
    if search not in original:
        return (False, original)
    mutated = original.replace(search, replace, 1)
    module_path.write_text(mutated, encoding="utf-8")
    return (True, original)


def restore_module(module_path: Path, original: str) -> None:
    module_path.write_text(original, encoding="utf-8")


def _run_pytest_x() -> tuple[int, int, float]:
    """Run pytest -x (stop on first failure).  Returns (passed, failed, duration_s)."""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest", "-x", "-q",
             "--tb=no", "--no-header", "-p", "no:cacheprovider"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SEC,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
    except subprocess.TimeoutExpired:
        # Treat hang as "killed by infinite loop" — a mutation that
        # makes tests hang is a real regression we want to surface.
        return (0, 1, float(PYTEST_TIMEOUT_SEC))
    duration = time.monotonic() - started
    out = (proc.stdout or "") + (proc.stderr or "")
    passed_m = re.search(r"(\d+) passed", out)
    failed_m = re.search(r"(\d+) failed", out)
    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    # With -x, pytest exits non-zero on first failure; if the suite all
    # passed, exit 0 + failed=0.  A non-zero exit with failed==0 means
    # a collection error — treat as "killed" since the mutation broke
    # collection itself.
    if proc.returncode != 0 and failed == 0:
        failed = 1
    return (passed, failed, duration)


def _pick_applicable_patterns(source: str,
                              mutation_count: int) -> list[tuple[str, str, str]]:
    """W11-MUTATION-PATTERN-EXPANSION 2026-05-25: pick the first N
    patterns whose search-string is actually present in *source*.

    Pre-W11 the canary picked MUTATIONS[:N] which often returned
    0/3 applicable on modules that didn't use those idioms (e.g.
    observer/cycle.py uses async/await but not the int-flip patterns
    at the head of MUTATIONS).

    Returns up to *mutation_count* applicable patterns; falls back to
    first N if no pattern matches (preserving prior behavior for
    "neutral pass" reporting on modules with no mutable idioms).
    """
    applicable = [
        (label, search, replace)
        for label, search, replace in MUTATIONS
        if search in source
    ]
    if applicable:
        return applicable[:mutation_count]
    # No matches: fall back to first N (canary will report all skipped)
    return list(MUTATIONS[:mutation_count])


def run_canary(module_rel: str, mutation_count: int = CANARY_MUTATION_COUNT) -> CanaryRun:
    """Apply *mutation_count* mutations to module and return CanaryRun."""
    module_path = REPO_ROOT / module_rel
    started = datetime.now(timezone.utc)
    run = CanaryRun(module=module_rel, started_at=started.isoformat())

    if not module_path.exists():
        print(f"[canary] module not found: {module_rel}", file=sys.stderr)
        # Synthesize a failed-to-apply placeholder so reports show the
        # missing module instead of silently producing zero results.
        for label, search, replace in MUTATIONS[:mutation_count]:
            run.results.append(CanaryResult(
                module=module_rel, label=label, pattern=search,
                applied=False, killed=False, failed_tests=0,
                duration_s=0.0,
                skipped_reason="module file not found",
            ))
        return run

    # W11-MUTATION-PATTERN-EXPANSION: pre-scan source for applicable
    # patterns so async-heavy modules pick await_call_strip /
    # async_to_sync_def instead of always reporting 0/3 on int-flip
    # patterns.
    source = module_path.read_text(encoding="utf-8", errors="replace")
    patterns_to_run = _pick_applicable_patterns(source, mutation_count)

    print(f"[canary] module: {module_rel}", file=sys.stderr)
    sweep_start = time.monotonic()
    for label, search, replace in patterns_to_run:
        applied, original = apply_mutation(module_path, search, replace)
        if not applied:
            print(f"  [{label}] pattern not present — skipping",
                  file=sys.stderr)
            run.results.append(CanaryResult(
                module=module_rel, label=label, pattern=search,
                applied=False, killed=False, failed_tests=0,
                duration_s=0.0,
                skipped_reason=f"pattern '{search}' not present in module",
            ))
            continue
        try:
            passed, failed, duration = _run_pytest_x()
        finally:
            restore_module(module_path, original)
        killed = failed > 0
        print(f"  [{label}] killed={killed} failed={failed} passed={passed} "
              f"duration={duration:.1f}s", file=sys.stderr)
        run.results.append(CanaryResult(
            module=module_rel, label=label, pattern=search,
            applied=True, killed=killed, failed_tests=failed,
            duration_s=duration,
        ))
    run.total_duration_s = time.monotonic() - sweep_start
    return run


# -- Reporting -------------------------------------------------------------


def format_report(run: CanaryRun) -> str:
    lines = [
        f"# Mutation canary — {run.module}",
        "",
        f"_Generated: {run.started_at}_",
        "",
        f"- Module: `{run.module}`",
        f"- Mutations applied: {run.applied_count}/{len(run.results)}",
        f"- Mutations killed: {run.killed_count}/{run.applied_count}"
        f" (canary {'PASS' if run.all_killed else 'FAIL'})",
        f"- Total duration: {run.total_duration_s:.1f}s",
        f"- Next module in rotation: `{run.next_module or '(unknown)'}`",
        "",
        "## Per-mutation results",
        "",
        "| Label | Applied | Killed | Failed Tests | Duration | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for r in run.results:
        applied_str = "yes" if r.applied else "no"
        killed_str = "yes" if r.killed else ("no" if r.applied else "—")
        failed_str = str(r.failed_tests) if r.applied else "—"
        duration_str = f"{r.duration_s:.1f}s" if r.applied else "—"
        notes = r.skipped_reason or ""
        lines.append(
            f"| `{r.label}` | {applied_str} | {killed_str} | {failed_str} | "
            f"{duration_str} | {notes} |"
        )
    lines.append("")
    if not run.all_killed:
        survived = [r for r in run.results if r.applied and not r.killed]
        lines.append("## SURVIVING MUTATIONS — regression signal\n")
        for r in survived:
            lines.append(f"- `{r.label}` survived; pattern `{r.pattern}` "
                         f"replaced without any test catching it. "
                         f"Recommended STATUS row: "
                         f"`W?-CANARY-{Path(r.module).stem}-{r.label}` to "
                         f"add an assertion that catches this mutation.")
        lines.append("")
    return "\n".join(lines)


def write_report(run: CanaryRun) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    module_stem = Path(run.module).stem
    out_path = REPORT_DIR / f"mutation_canary_{stamp}_{module_stem}.md"
    out_path.write_text(format_report(run), encoding="utf-8")
    return out_path


# -- CLI -------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default=None,
                        help="Module path to canary (overrides rotation).")
    parser.add_argument("--count", type=int, default=CANARY_MUTATION_COUNT,
                        help=f"Number of mutations to apply "
                        f"(default {CANARY_MUTATION_COUNT}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the module that would be tested + exit 0.")
    parser.add_argument("--no-advance", action="store_true",
                        help="Don't advance rotation pointer after run.")
    args = parser.parse_args()

    module = args.module or load_rotation_state()
    if args.dry_run:
        print(f"[canary] would test: {module}")
        print(f"[canary] next after: {advance_rotation(module)}")
        return 0

    run = run_canary(module, mutation_count=args.count)
    run.next_module = advance_rotation(module)

    out_path = write_report(run)
    print(f"\n[canary] report: {out_path}", file=sys.stderr)
    print(f"[canary] module: {run.module}", file=sys.stderr)
    print(f"[canary] applied: {run.applied_count}/{len(run.results)}",
          file=sys.stderr)
    print(f"[canary] killed: {run.killed_count}/{run.applied_count}",
          file=sys.stderr)
    print(f"[canary] duration: {run.total_duration_s:.1f}s", file=sys.stderr)

    if not args.no_advance and args.module is None:
        # Only advance the rotation if we used it (not an explicit
        # --module override).
        save_rotation_state(run.next_module)
        print(f"[canary] next module: {run.next_module}", file=sys.stderr)

    if not run.all_killed:
        print(f"\n*** CANARY FAILED — {len(run.results) - run.killed_count} "
              f"mutation(s) survived.  Add assertions or improve test "
              f"coverage on {run.module}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
