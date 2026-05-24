"""Retry the 9 failed Round 2 personas with a SMALLER evidence subset.

Round 2 main run had 9/20 personas (mostly Kimi) come back empty because
the 63KB evidence pack overshot Kimi's context.  This script ships
ONLY the post-fix proof evidence (CLI outputs + dashboard endpoints +
the W12-A commit log) — 4-5 KB instead of 63KB.
"""

from __future__ import annotations

import concurrent.futures as _cf
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

EVIDENCE_DIR = REPO / "coord" / "reviews" / "operator-review-20agents-round2" / "evidence"
OUTPUT_DIR = REPO / "coord" / "reviews" / "operator-review-20agents-round2"

# Only the files DIRECTLY proving (or refuting) the W12-A fixes
RETRY_EVIDENCE_FILES = [
    "03_observer_watchdog.txt",
    "09_dashboard_apis_w12.txt",
    "04_preflight.txt",
    "06_harness_help.txt",
    "15_agent_init_dry.txt",
    "21_w12_a_commit.txt",
]

FAILED_PERSONAS = [
    ("K01-fresh-agent", "kimi", "kimi-for-coding"),
    ("K02-operator-cli", "kimi", "kimi-for-coding"),
    ("K03-non-technical-operator", "kimi", "kimi-for-coding"),
    ("K04-dashboard-ux", "kimi", "kimi-for-coding"),
    ("K05-security", "kimi", "kimi-for-coding"),
    ("K10-real-day-of-use", "kimi", "kimi-for-coding"),
    ("M05-test-use-blockers", "mimo", "mimo-v2.5-pro"),
    ("M06-wave-12-priorities", "mimo", "mimo-v2.5-pro"),
    ("M10-stop-or-ship", "mimo", "mimo-v2.5-pro"),
]


def _load_small_evidence() -> str:
    parts: list[str] = []
    for name in RETRY_EVIDENCE_FILES:
        path = EVIDENCE_DIR / name
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Truncate to 4000 chars per file
            if len(text) > 4000:
                text = text[:4000] + "\n[...truncated...]\n"
        except OSError:
            continue
        parts.append(f"\n=== {name} ===\n{text}")
    return "".join(parts)


def _build_prompt(persona_id: str, engine: str, evidence: str) -> str:
    return f"""You are persona **{persona_id}** ({engine}).  In Round 1 of
the operator-review panel you voted WAIT-FOR-WAVE-12 because of 3
universal blockers:

  1. Windows cp1252 Unicode crash in preflight + --help + agent init
  2. Dashboard 404s on /api/cost + /api/preflight-latency +
     /api/l5-events + /api/loop
  3. Watchdog jargon (raw `stale_seconds: 1209.65` with no context) +
     loop staleness invisible in `harness today`

Wave 12-A shipped commit `60ecfcf` claiming to fix all three.  Here is
focused POST-fix evidence (CLI outputs + dashboard API responses + the
commit log):

{evidence}

## Your task

Output EXACTLY these sections, in this order:

### Verdict shift
One of: `READY` (proven fixed) | `STILL-NEEDS-WORK` (partial / new gap)
| `WORSE` (regression)

### Per-blocker assessment
For each of the 3 Round-1 blockers, state PROVEN-FIXED / PARTIAL /
NOT-FIXED + one sentence grounding it in evidence.

### Operator vote
One of: `APPROVE-AND-SHIP` | `WAIT-FOR-WAVE-12-B` | `ESCALATE-TO-HUMAN`

### Single grounding quote
ONE verbatim quote (<25 words) from the evidence above.

Be brutally honest.  Output Markdown.
"""


def _dispatch_one(persona_id: str, engine: str, model: str,
                   evidence: str) -> dict:
    out_path = OUTPUT_DIR / "responses" / f"{persona_id}_response.md"
    started = time.monotonic()
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        return {"persona_id": persona_id, "ok": False,
                "error": str(exc), "elapsed_s": time.monotonic() - started}
    prompt = _build_prompt(persona_id, engine, evidence)
    try:
        resp = eng.dispatch(prompt, model, {"max_tokens": 1200})
    except Exception as exc:
        return {"persona_id": persona_id, "ok": False,
                "error": str(exc), "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        return {"persona_id": persona_id, "ok": False,
                "error": resp.error or "(empty)", "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"persona_id": persona_id, "ok": True, "elapsed_s": elapsed}


def main() -> int:
    evidence = _load_small_evidence()
    print(f"[retry] evidence: {len(evidence)} chars "
          f"({len(RETRY_EVIDENCE_FILES)} files), "
          f"{len(FAILED_PERSONAS)} personas")
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_dispatch_one, pid, engine, model, evidence): pid
            for pid, engine, model in FAILED_PERSONAS
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r.get('elapsed_s', 0):.1f}s"
                     if r["ok"]
                     else (r.get("error") or "(none)")[:60])
            print(f"[retry] {flag} {r['persona_id']:<32}  {extra}")
            results.append(r)
    n_ok = sum(1 for r in results if r["ok"])
    print(f"\n[retry] {n_ok}/{len(results)} successful")
    return 0


if __name__ == "__main__":
    sys.exit(main())
