"""W5-TT 2026-05-23: 5-MiMo session review.

Operator request: 'deploy 5 mimo engines to read all our conversations
this session, and share their findings opinions directives'.

Sends the compact session arc to 5 MiMo Pro v2.5 agents, each with a
distinct reviewer persona, then writes outputs for the operator to
read. Synthesis is a separate step (sixth dispatch) — keeps each
reviewer independent.

Personas (so different agents surface different issues):
  1. Skeptical Engineer  — what's wrong, broken, over-engineered
  2. Operator Advocate   — UX gaps, friction, missing affordances
  3. Architect           — structural debt, future-risk patterns
  4. Product Manager     — scope/value/priority calibration
  5. QA Specialist       — testing gaps, edge cases, regression risks

Sequential dispatch (parallel can rate-limit Token Plan).  Each
response writes to coord/reviews/external/<stamp>_review_<persona>.md.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


ARC_PATH = Path("coord/reviews/session_arc_compact.md")
OUT_DIR = Path("coord/reviews/external")


@dataclass(frozen=True)
class Reviewer:
    persona: str
    label: str
    framing: str


REVIEWERS: list[Reviewer] = [
    Reviewer(
        persona="skeptical_engineer",
        label="Skeptical Engineer",
        framing=(
            "You are a senior engineer reviewing this session for "
            "OVER-ENGINEERING, BROKEN ABSTRACTIONS, and FAULTY ASSUMPTIONS. "
            "You're skeptical by default. Cite specific commit IDs / verbs. "
            "Focus on what you'd reject in a PR review."
        ),
    ),
    Reviewer(
        persona="operator_advocate",
        label="Operator Advocate",
        framing=(
            "You represent the operator. You care about UX, friction, "
            "discoverability, and 'will the operator actually use this'. "
            "Identify where the harness adds work instead of removing it. "
            "Flag any feature that requires reading source to understand."
        ),
    ),
    Reviewer(
        persona="architect",
        label="Software Architect",
        framing=(
            "You are reviewing the SYSTEMIC HEALTH of the harness "
            "architecture after this session. Identify accumulating "
            "complexity, future-risk patterns (will this scale to 10 "
            "engines? 100 spec files?), and missing abstractions. "
            "Distinguish 'shipped now' from 'will hurt in 3 months'."
        ),
    ),
    Reviewer(
        persona="product_manager",
        label="Product Manager",
        framing=(
            "You are responsible for PRIORITY DISCIPLINE. Review whether "
            "the session's commits delivered against the operator's "
            "stated priorities, or drifted into adjacent work. Flag "
            "scope-creep, premature optimization, and bikeshedding. "
            "What should have been deferred? What was MISSED?"
        ),
    ),
    Reviewer(
        persona="qa_specialist",
        label="QA Specialist",
        framing=(
            "You audit TESTING DISCIPLINE. Identify code paths that "
            "shipped without adequate test coverage, edge cases not "
            "exercised, and regression risks. Flag any tests that look "
            "tautological (re-test what they assert). Comment on the "
            "1422-test count: signal vs noise."
        ),
    ),
]


PROMPT_TEMPLATE = """\
You are {label} reviewing a Claude Code session that produced 24 git
commits on the xaxiu-harness project on 2026-05-23.

Your specific framing for this review:
{framing}

Below is the compact session arc: tool-call counts, all operator
messages verbatim, and the commit-log line for each shipped change.

Your task — write a candid review (~400-600 words) covering:

1. **Top 3 concerns** in your domain (be specific; cite commit IDs).
2. **What was done right** (steal-with-pride patterns).
3. **One direct DIRECTIVE** to the dev team for the next session — a
   single concrete action you would mandate if you had authority.
4. **Confidence level** (0.0-1.0) that the session's output is
   production-ready given your domain lens.

Be opinionated. Bland reviews are worthless. If something is wrong,
say so. If something is brilliant, say that too.

Output markdown only, no preamble or code-fence wrapping.

# Session arc

{arc}
"""


def main() -> int:
    if not ARC_PATH.exists():
        print(f"arc missing: {ARC_PATH}", file=sys.stderr)
        print("Run: python scripts/extract_session_arc.py", file=sys.stderr)
        return 1
    arc = ARC_PATH.read_text(encoding="utf-8")
    print(f"[review] arc: {len(arc)} chars  ({len(REVIEWERS)} reviewers)",
          flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: list[dict] = []

    for rv in REVIEWERS:
        print(f"\n[review] {rv.label} ({rv.persona})...", flush=True)
        prompt = PROMPT_TEMPLATE.format(
            label=rv.label, framing=rv.framing, arc=arc,
        )
        eng = get_engine("mimo", prefer_dpapi=False)
        started = time.monotonic()
        try:
            resp = eng.dispatch(prompt, "mimo-v2.5-pro", {"max_tokens": 32_000})
            latency = int((time.monotonic() - started) * 1000)
            ok = bool(resp.success and (resp.text or "").strip())
            text = resp.text or ""
            err = resp.error
            tokens_in = getattr(resp, "tokens_in", 0)
            tokens_out = getattr(resp, "tokens_out", 0)
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            ok, text, err = False, "", f"{type(exc).__name__}: {exc}"
            tokens_in = tokens_out = 0

        out_path = OUT_DIR / f"{stamp}_session_review_{rv.persona}.md"
        if ok:
            out_path.write_text(
                f"<!-- engine=mimo model=mimo-v2.5-pro success=True "
                f"latency_ms={latency} tokens_in={tokens_in} "
                f"tokens_out={tokens_out} persona={rv.persona} -->\n\n"
                f"# Review by {rv.label}\n\n{text}",
                encoding="utf-8",
            )
            print(f"  ✓ {latency}ms ({len(text)} chars, "
                  f"{tokens_out} tokens out) → {out_path}",
                  flush=True)
            results.append({
                "persona": rv.persona, "label": rv.label,
                "ok": True, "latency_ms": latency,
                "chars": len(text), "tokens_in": tokens_in,
                "tokens_out": tokens_out, "path": str(out_path),
            })
        else:
            out_path.write_text(
                f"FAILED engine=mimo persona={rv.persona} "
                f"latency_ms={latency} error={err}\n",
                encoding="utf-8",
            )
            print(f"  ✗ {latency}ms error={err}", flush=True)
            results.append({
                "persona": rv.persona, "label": rv.label,
                "ok": False, "latency_ms": latency,
                "error": err, "path": str(out_path),
            })

    manifest = OUT_DIR / f"session_review_5mimo_manifest_{stamp}.json"
    manifest.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "arc_chars": len(arc),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\n[review] manifest: {manifest}", flush=True)
    ok_count = sum(1 for r in results if r.get("ok"))
    print(f"[review] {ok_count}/{len(results)} reviewers returned",
          flush=True)
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
