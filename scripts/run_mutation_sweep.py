"""W6-A3 mutation sweep — QA-directive verification of test-suite teeth.

For each of the top-5 hot modules (chosen by the W6 review board:
dispatcher.py, concrete.py, worker.py, integrator.py, orchestrator.py),
apply 5 single-line mutations, run the test suite, count failures,
restore.  Acceptance threshold: ≥3 tests must fail per mutation on
average.  A module that doesn't meet the bar gets a follow-up
STATUS row recommending real-assertion work.

Usage:
    PYTHONPATH=src python -X utf8 scripts/run_mutation_sweep.py

Writes:
    coord/reviews/mutation_sweep_20260523.md   (or the date arg)

The mutations are *single string-replace* substitutions chosen for
semantic impact + low collision risk.  Each is applied atomically
(read original, write mutated, run pytest, restore original) so a
KeyboardInterrupt mid-run leaves the tree clean on retry.

To stay deterministic, the script uses str.replace(..., count=1) on
the source.  If a pattern doesn't appear in the file, the mutation
is reported as ``skipped`` (uninteresting — no mutant to evaluate)
rather than counted as a failure.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Each module gets the same 5-mutation template — these are the
# "smoke" mutations that should impact at least one test if the
# coverage is real.
MUTATIONS: list[tuple[str, str, str]] = [
    # (label, search, replace)
    ("bool_return_flip",       "return True",   "return False"),
    ("eq_to_neq",              " == ",          " != "),
    ("gt_to_ge",               " > 0",          " >= 0"),
    ("is_not_none_to_is_none", "is not None",   "is None"),
    ("plus1_to_minus1",        " + 1",          " - 1"),
]

MODULES: list[str] = [
    "src/harness/engines/dispatcher.py",
    "src/harness/engines/concrete.py",
    "src/harness/coord/worker.py",
    "src/harness/coord/integrator.py",
    "src/harness/orchestrator.py",
]


@dataclass(frozen=True)
class MutantResult:
    module: str
    label: str
    pattern: str
    applied: bool
    failed_tests: int
    passed_tests: int
    duration_s: float


def _run_pytest_quick() -> tuple[int, int, float]:
    """Run pytest -q and return (passed, failed, duration_s).

    Uses ``-x`` to stop on first failure for speed?  No — we need
    the total failure count, so let pytest run to completion.
    But we DO use ``--tb=no`` and a tight timeout so a buggy mutant
    that hangs doesn't stall the sweep.
    """
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "--tb=no",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
    except subprocess.TimeoutExpired:
        return (0, 999, 300.0)  # treat hangs as 999 failures
    duration = (datetime.now(timezone.utc) - started).total_seconds()

    # pytest summary line: "1426 passed in 87.33s" or
    # "5 failed, 1421 passed in 87.33s"
    out = proc.stdout + proc.stderr
    passed_m = re.search(r"(\d+) passed", out)
    failed_m = re.search(r"(\d+) failed", out)
    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    return (passed, failed, duration)


def _apply_mutation(module_path: Path, search: str, replace: str) -> tuple[bool, str]:
    """Read module, replace first occurrence, write.  Returns
    (applied, original_text).  applied=False if pattern absent."""
    original = module_path.read_text(encoding="utf-8")
    if search not in original:
        return (False, original)
    mutated = original.replace(search, replace, 1)
    module_path.write_text(mutated, encoding="utf-8")
    return (True, original)


def _restore(module_path: Path, original: str) -> None:
    module_path.write_text(original, encoding="utf-8")


def run_sweep() -> list[MutantResult]:
    results: list[MutantResult] = []
    for rel in MODULES:
        module_path = REPO_ROOT / rel
        if not module_path.exists():
            print(f"[sweep] skip missing module: {rel}", file=sys.stderr)
            continue
        print(f"\n[sweep] module: {rel}", file=sys.stderr)
        for label, search, replace in MUTATIONS:
            applied, original = _apply_mutation(module_path, search, replace)
            if not applied:
                print(f"  [{label}] pattern not present — skipping",
                      file=sys.stderr)
                results.append(MutantResult(
                    module=rel, label=label, pattern=search,
                    applied=False, failed_tests=0, passed_tests=0,
                    duration_s=0.0,
                ))
                continue
            try:
                passed, failed, duration = _run_pytest_quick()
            finally:
                _restore(module_path, original)
            print(f"  [{label}] failed={failed} passed={passed} "
                  f"duration={duration:.1f}s",
                  file=sys.stderr)
            results.append(MutantResult(
                module=rel, label=label, pattern=search,
                applied=True, failed_tests=failed, passed_tests=passed,
                duration_s=duration,
            ))
    return results


def write_report(results: list[MutantResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# W6-A3 mutation sweep — top-5 hot modules\n")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n")
    lines.append("Each mutation is a single-line string-replace applied via "
                 "`str.replace(..., count=1)`, then `pytest -q` is run "
                 "against the full suite, then the original file is restored.\n")
    lines.append("**Acceptance threshold** (per W6-A3 spec): "
                 "≥3 tests must fail per mutation on average.\n")
    lines.append("## Mutations applied\n")
    lines.append("| Label | Search | Replace |")
    lines.append("|---|---|---|")
    for label, search, replace in MUTATIONS:
        lines.append(f"| `{label}` | `{search}` | `{replace}` |")
    lines.append("")
    lines.append("## Per-module results\n")
    # Group by module
    by_module: dict[str, list[MutantResult]] = {}
    for r in results:
        by_module.setdefault(r.module, []).append(r)
    failing_modules: list[str] = []
    for module, mrs in by_module.items():
        applied = [r for r in mrs if r.applied]
        avg_failed = (sum(r.failed_tests for r in applied) / len(applied)
                      if applied else 0.0)
        meets_bar = avg_failed >= 3.0
        if not meets_bar:
            failing_modules.append(module)
        verdict = "PASS" if meets_bar else "FAIL"
        lines.append(f"### `{module}`  → {verdict} (avg failed = "
                     f"{avg_failed:.1f})\n")
        lines.append("| Mutation | Applied | Failed | Passed | Duration |")
        lines.append("|---|---|---|---|---|")
        for r in mrs:
            applied_str = "✓" if r.applied else "(pattern absent)"
            failed_str = str(r.failed_tests) if r.applied else "—"
            passed_str = str(r.passed_tests) if r.applied else "—"
            duration_str = f"{r.duration_s:.1f}s" if r.applied else "—"
            lines.append(
                f"| `{r.label}` | {applied_str} | {failed_str} | "
                f"{passed_str} | {duration_str} |"
            )
        lines.append("")
    lines.append("## Summary\n")
    if failing_modules:
        lines.append("Modules NOT meeting the ≥3-tests-failed threshold "
                     "(follow-up STATUS rows recommended for real-assertion "
                     "work):\n")
        for m in failing_modules:
            lines.append(f"- `{m}`")
        lines.append("")
    else:
        lines.append("All modules met the ≥3-tests-failed acceptance "
                     "threshold.\n")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[sweep] report written: {out_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None,
                        help="YYYYMMDD date for report filename "
                        "(defaults to today UTC)")
    args = parser.parse_args()
    date_str = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = REPO_ROOT / "coord" / "reviews" / f"mutation_sweep_{date_str}.md"

    results = run_sweep()
    write_report(results, out_path)

    # Exit 1 if any module failed the bar — operator-visible signal.
    by_module: dict[str, list[MutantResult]] = {}
    for r in results:
        by_module.setdefault(r.module, []).append(r)
    for module, mrs in by_module.items():
        applied = [r for r in mrs if r.applied]
        if not applied:
            continue
        avg_failed = sum(r.failed_tests for r in applied) / len(applied)
        if avg_failed < 3.0:
            print(f"[sweep] module {module} below threshold "
                  f"(avg_failed={avg_failed:.1f} < 3)", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
