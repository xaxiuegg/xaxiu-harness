"""20-agent audit panel (10 Kimi + 10 MiMo) for a single W-action.

Operator directive 2026-05-25 (mid-W11-C): every W-action commit
needs a 20-persona retroactive + active audit on top of the existing
avg-of-N MiMo single-engine gate.  Surfaces qualitatively different
signal: 20 distinct lenses (correctness / test-quality / API surface
/ safety / backwards-compat / etc.) vs the existing "is the spec
met?" lens.

Usage:
    PYTHONPATH=src python -X utf8 scripts/audit_w_action_panel20.py \\
      <task-id> --commit <sha>

Output:
    coord/reviews/w-action-audits/<stamp>_<task-id>_panel20.md

The panel TOLERATES per-persona failures (MiMo content filter trips
on prompts that name API keys verbatim — known W10 issue).  Panel
verdict gates on >=15 of 20 successful responses + mean confidence
>= 0.7.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

# Reuse the existing audit script's helpers
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from audit_task_with_mimo import (  # noqa: E402
    _resolve_plan_path,
    git_commits_info,
    load_acceptance,
    parse_audit_response,
)

from harness.engines.concrete import get_engine  # noqa: E402


OUT_DIR = REPO_ROOT / "coord" / "reviews" / "w-action-audits"
PANEL_PASS_GATE = 0.7  # mean confidence threshold
MIN_SUCCESSFUL_PERSONAS = 15  # of 20


# -- 10 Kimi personas (different lenses) ---------------------------------


KIMI_PERSONAS: list[tuple[str, str]] = [
    ("K01-correctness",
     "CORRECTNESS REVIEWER.  Does this commit do what the spec says? "
     "Cross-check every acceptance criterion against the code; flag any "
     "criterion that is partially-met or interpreted-creatively."),
    ("K02-test-quality",
     "TEST QUALITY REVIEWER.  Are the tests REAL — do they exercise the "
     "feature end-to-end?  Or are they happy-path stubs that would pass "
     "even if the impl was hollow?  Look for: missing edge cases, "
     "rubber-stamp mocks, assertion strength."),
    ("K03-api-surface",
     "API SURFACE REVIEWER.  For agent-callable code (CLI verbs, SDK "
     "functions, helpers): is the signature clean?  Are defaults sane?  "
     "Will an agent reading the docstring + signature use this correctly "
     "on first try?  Or are there footguns?"),
    ("K04-error-handling",
     "ERROR HANDLING REVIEWER.  Every failure mode covered with the "
     "right exception type?  Operator-friendly messages (not stack traces)?  "
     "L4/L5 escalation tags where appropriate?  Silent-except patterns "
     "audited per W9-SILENT-EXCEPTION-AUDIT?"),
    ("K05-backwards-compat",
     "BACKWARDS-COMPAT REVIEWER.  Does this commit break any existing "
     "caller?  Look at: function signatures, return types, exception "
     "types, env-var behavior, CLI flag defaults.  Note: this harness "
     "has 46+ DispatchResult callers + 81 .text-readers; any schema "
     "change must be feature-flag-gated."),
    ("K06-documentation",
     "DOCUMENTATION REVIEWER.  Docstrings match impl?  Spec file "
     "updated?  README / runbook reflects new behavior?  Agent reading "
     "ONLY the docstrings + spec would understand what this verb does?"),
    ("K07-performance",
     "PERFORMANCE REVIEWER.  Any hot-path concerns?  Latency-sensitive "
     "code (dispatch, preflight)?  Cache locality / file I/O patterns?  "
     "Per-check budget honored (W9-CLI-TIMEOUT-BUDGET)?"),
    ("K08-dependencies",
     "DEPENDENCIES REVIEWER.  Any new pip package?  Is it justified?  "
     "Minimal alternative considered (stdlib first per W9-STATE-FILE-LOCK "
     "precedent)?  Cross-platform?"),
    ("K09-security",
     "SECURITY REVIEWER.  Credential handling correct?  No env-var "
     "value leaks (per [[feedback_no_env_value_leak]] memory)?  Redaction "
     "patterns honored (W9-REDACTION-INTEGRITY-TEST)?  Injection paths "
     "(SQL, shell, path traversal)?"),
    ("K10-scope-creep",
     "DEAD CODE / SCOPE CREEP REVIEWER.  Anything in this commit that "
     "isn't actually USED yet?  Premature abstractions?  TODOs / FIXMEs "
     "that should be real W12 candidates?  Test fixtures that aren't "
     "referenced?  Code that just adds maintenance burden?"),
]


# -- 10 MiMo personas (different lenses) ---------------------------------


MIMO_PERSONAS: list[tuple[str, str]] = [
    ("M01-architecture",
     "ARCHITECTURE REVIEWER.  Does this fit the harness's existing "
     "patterns?  Or does it introduce a new layering that fights with "
     "what's already there?  Cite the pattern (operator/, observer/, "
     "engines/, coord/, state/) it most resembles."),
    ("M02-safety",
     "SAFETY REVIEWER.  State corruption risk?  Race conditions across "
     "ThreadPoolExecutor / asyncio / multiprocessing?  Atomic-write "
     "honored (W9-STATE-ATOMIC-WRITES)?  File locks (W9-STATE-FILE-LOCK) "
     "needed but not used?"),
    ("M03-operator-ux",
     "OPERATOR UX REVIEWER.  CLI clarity (help text, exit codes, error "
     "messages)?  Plain-language verdicts (per W10-PREFLIGHT-EXIT-CODE-"
     "SEMANTICS)?  Remediation hints (W10-PREFLIGHT-REMEDIATION-CARDS)?"),
    ("M04-cross-platform",
     "CROSS-PLATFORM REVIEWER.  Works on Windows + Linux + Mac?  Any "
     "Windows-only assumption (DPAPI, Task Scheduler, CRLF) that breaks "
     "non-Windows agents?  Per W11-DPAPI-CROSS-PLATFORM precedent."),
    ("M05-agent-ux",
     "AGENT UX REVIEWER.  Does this make an agentic coding agent's job "
     "easier?  Specifically: does it preserve operator-agent context "
     "window?  Maximize subscription-engine offload?  Pre-W11 pivot "
     "spec verbatim: 'maximize % of tokens offloaded while preserving "
     "the agent's own context window'."),
    ("M06-audit-criteria",
     "AUDIT-GATE APPROPRIATENESS REVIEWER.  Are the acceptance criteria "
     "in the spec testable + meaningful?  Or vague / aspirational?  "
     "Would a different sensible engineer interpret them the same way?"),
    ("M07-spec-drift",
     "SPEC-DRIFT REVIEWER.  Is the implementation faithful to the spec?  "
     "Where it deviates (split rows / merged rows / feature-flag "
     "deferrals), is the deviation documented in STATUS.csv and the "
     "spec file?"),
    ("M08-forward-compat",
     "FORWARD-COMPAT REVIEWER.  What does this commit lock in for W12+?  "
     "Will any decision here be expensive to reverse?  Is there a "
     "cleaner version that should ship instead?"),
    ("M09-code-review",
     "CODE REVIEW REVIEWER.  Style / readability concerns?  Function "
     "length?  Cyclomatic complexity?  Naming?  Modularity?  Anything "
     "that a junior engineer would have to ask the author about?"),
    ("M10-regression-risk",
     "REGRESSION RISK REVIEWER.  What's the worst-case failure mode "
     "introduced by this commit?  How would it surface (test failure / "
     "silent state corruption / engine timeout / agent confusion)?  Is "
     "there a guardrail catching it?"),
]


# -- per-persona prompt template ----------------------------------------


PERSONA_PROMPT = """\
You are PERSONA {persona_id}: {persona_lens}

You are reviewing a single Wave 11 task that just shipped in xaxiu-harness.

# Task: {task_id}

# Acceptance criteria (from {plan_path})

{acceptance}

# Commit context

SHA:    {sha}
Author: {author}
Date:   {date}
Message:
{message}

# Files changed

{diffstat}

# Diff

```
{diff_excerpt}
```

# Current state of modified files (post-commit)

{file_contents}

# Your task

From YOUR specific lens, audit this commit.  Be concise + concrete.
Don't restate the spec; identify what the spec asks AND what the
commit actually does, then judge the gap.

Output JSON ONLY (no prose, no markdown fence):

{{
  "persona_id": "{persona_id}",
  "lens_finding": "<one sentence from your lens — what did you see>",
  "criteria_gap": "<specific gap if any, or 'none'>",
  "blocking_concern": "<the one issue that would make you say STOP, or 'none'>",
  "confidence": 0.0,
  "verdict": "PASS" | "STOP"
}}

Confidence scale:
  0.9-1.0  No concern from your lens; criterion fully met
  0.7-0.9  Minor concern (acceptable to proceed)
  0.5-0.7  Real concern (PASS-WITH-CONCERN; flag for followup)
  0.0-0.5  Blocking from your lens (STOP)

Gate: mean confidence across 20 personas < 0.7 = STOP.  Each persona
votes ONLY from their lens; aggregation happens externally.
"""


@dataclass
class PersonaVerdict:
    persona_id: str
    engine: str
    success: bool
    confidence: float = 0.0
    verdict: str = "?"
    lens_finding: str = ""
    criteria_gap: str = ""
    blocking_concern: str = ""
    latency_ms: int = 0
    error: str | None = None
    raw_text: str = ""


def _dispatch_persona(engine_name: str, model: str,
                       persona_id: str, persona_lens: str,
                       base_prompt: str) -> PersonaVerdict:
    """Run one persona's audit; never raises (errors captured in verdict)."""
    started = time.monotonic()
    prompt = base_prompt.replace("{persona_id}", persona_id).replace(
        "{persona_lens}", persona_lens,
    )
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return PersonaVerdict(
            persona_id=persona_id, engine=engine_name,
            success=False, error=f"engine init failed: {exc}",
        )
    resp = eng.dispatch(prompt, model, {"max_tokens": 1500})
    latency = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return PersonaVerdict(
            persona_id=persona_id, engine=engine_name,
            success=False, latency_ms=latency,
            error=f"engine returned empty/error: {resp.error}",
        )
    text = resp.text.strip()
    # MiMo content filter check
    if ("rejected" in text.lower() and "high risk" in text.lower()):
        return PersonaVerdict(
            persona_id=persona_id, engine=engine_name,
            success=False, latency_ms=latency,
            error="rejected by content filter", raw_text=text,
        )
    conf, verdict, parsed = parse_audit_response(text)
    return PersonaVerdict(
        persona_id=persona_id, engine=engine_name,
        success=True, confidence=conf, verdict=verdict,
        lens_finding=parsed.get("lens_finding", "")[:300],
        criteria_gap=parsed.get("criteria_gap", "")[:300],
        blocking_concern=parsed.get("blocking_concern", "")[:300],
        latency_ms=latency, raw_text=text,
    )


def run_panel(task_id: str, commit: str,
              plan_override: str | None = None) -> dict:
    """Fire the 20-persona panel; return a structured summary dict."""
    # Resolve plan + acceptance criteria.
    # W13-AUDIT-INFRA-W13-PLUS 2026-05-25: W12+ task ids resolve to
    # coord/STATUS.csv; load_acceptance reads the row's Notes column.
    plan_path = _resolve_plan_path(task_id, plan_override)
    if not plan_path.exists():
        return {
            "task_id": task_id, "commit": commit,
            "panel_verdict": "ERROR",
            "error": f"plan not found: {plan_path}",
            "verdicts": [], "mean_confidence": 0.0,
            "successful_personas": 0, "total_personas": 0,
            "pass_count": 0, "stop_count": 0, "elapsed_sec": 0,
        }
    acceptance = load_acceptance(task_id, plan_path)
    if not acceptance:
        return {
            "task_id": task_id, "commit": commit,
            "panel_verdict": "ERROR",
            "error": f"task {task_id} not found in plan {plan_path}",
            "verdicts": [], "mean_confidence": 0.0,
            "successful_personas": 0, "total_personas": 0,
            "pass_count": 0, "stop_count": 0, "elapsed_sec": 0,
        }
    info = git_commits_info([commit])

    base_prompt = PERSONA_PROMPT.format(
        persona_id="{persona_id}",
        persona_lens="{persona_lens}",
        task_id=task_id,
        plan_path=plan_path,
        acceptance=acceptance,
        sha=info["sha"][:12],
        author=info["author"],
        date=info["date"],
        message=info["message"],
        diffstat=info["diffstat"][:2000],
        diff_excerpt=info["diff_excerpt"],
        file_contents=info.get("file_contents", "(none)"),
    )

    # Cap concurrency: 10 should be safe across both engines
    started = time.monotonic()
    verdicts: list[PersonaVerdict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = []
        for pid, lens in KIMI_PERSONAS:
            futures.append(pool.submit(
                _dispatch_persona, "kimi", "kimi-for-coding", pid, lens,
                base_prompt,
            ))
        for pid, lens in MIMO_PERSONAS:
            futures.append(pool.submit(
                _dispatch_persona, "mimo", "mimo-v2.5-pro", pid, lens,
                base_prompt,
            ))
        for f in as_completed(futures):
            verdicts.append(f.result())
    elapsed = time.monotonic() - started

    successful = [v for v in verdicts if v.success]
    mean_conf = (sum(v.confidence for v in successful) / len(successful)
                 if successful else 0.0)
    pass_count = sum(1 for v in successful if v.confidence >= 0.7)
    stop_count = sum(1 for v in successful if v.confidence < 0.7)
    panel_verdict = (
        "PASS" if (len(successful) >= MIN_SUCCESSFUL_PERSONAS
                   and mean_conf >= PANEL_PASS_GATE)
        else "STOP"
    )
    return {
        "task_id": task_id,
        "commit": info["sha"][:12],
        "panel_verdict": panel_verdict,
        "mean_confidence": round(mean_conf, 3),
        "pass_count": pass_count,
        "stop_count": stop_count,
        "successful_personas": len(successful),
        "total_personas": len(verdicts),
        "elapsed_sec": round(elapsed, 1),
        "verdicts": [asdict(v) for v in verdicts],
    }


def _format_report(panel: dict) -> str:
    pv = panel["panel_verdict"]
    lines = [
        f"# 20-agent audit panel — {panel['task_id']} ({panel['commit']})",
        "",
        f"<!-- engine=20-panel task={panel['task_id']} "
        f"sha={panel['commit']} mean_confidence={panel.get('mean_confidence', 0)} "
        f"verdict={pv} -->",
        "",
        f"- **Verdict**: {pv}",
        f"- Mean confidence: {panel.get('mean_confidence', 0)}",
        f"- Personas passing (≥0.7): {panel.get('pass_count', 0)} / "
        f"{panel.get('successful_personas', 0)} (of "
        f"{panel.get('total_personas', 0)} dispatched)",
        f"- Personas stopping (<0.7): {panel.get('stop_count', 0)}",
        f"- Elapsed: {panel.get('elapsed_sec', 0)}s",
        "",
    ]
    if "error" in panel:
        lines.append(f"\n**ERROR**: {panel['error']}")
        return "\n".join(lines)
    # Per-persona table
    lines.extend([
        "## Per-persona verdicts",
        "",
        "| Persona | Engine | Conf | Verdict | Lens finding |",
        "|---|---|---|---|---|",
    ])
    for v in sorted(panel["verdicts"], key=lambda x: x["persona_id"]):
        success_marker = "" if v["success"] else " (FAIL)"
        conf_str = f"{v['confidence']:.2f}" if v["success"] else "—"
        # Defensive: lens_finding can be None (persona returned JSON
        # with null) or missing; error can also be None.  Coerce to "".
        lens = (v.get("lens_finding") or v.get("error") or "")
        lens = str(lens)[:80].replace("|", "\\|")
        lines.append(
            f"| {v['persona_id']}{success_marker} | {v['engine']} | "
            f"{conf_str} | {v['verdict']} | {lens} |"
        )
    lines.append("")
    # Blocking concerns (only personas who returned STOP)
    blockers = [v for v in panel["verdicts"]
                if v.get("success") and v.get("confidence", 1.0) < 0.7]
    if blockers:
        lines.extend([
            "## Blocking concerns (personas with conf < 0.7)",
            "",
        ])
        for v in blockers:
            concern = (v.get("blocking_concern")
                       or v.get("lens_finding") or "(no concern text)")
            lines.append(
                f"- **{v['persona_id']}** ({v['confidence']:.2f}): "
                f"{str(concern)[:300]}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", help="W-action task id (e.g. W11-AGENT-INIT-VERB)")
    parser.add_argument("--commit", default="HEAD",
                        help="Commit SHA to audit (default HEAD).")
    parser.add_argument("--plan", default=None,
                        help="Override plan file path.")
    parser.add_argument("--json", action="store_true",
                        help="Emit raw JSON instead of pretty markdown.")
    args = parser.parse_args()

    panel = run_panel(args.task_id, args.commit, args.plan)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"{stamp}_{args.task_id}_panel20.md"
    out_path.write_text(_format_report(panel), encoding="utf-8")

    pv = panel.get("panel_verdict", "ERROR")
    print(f"[panel20] {args.task_id} {pv} "
          f"mean={panel.get('mean_confidence', 0)} "
          f"pass={panel.get('pass_count', 0)}/{panel.get('successful_personas', 0)} "
          f"elapsed={panel.get('elapsed_sec', 0)}s",
          file=sys.stderr)
    print(f"[panel20] report: {out_path}", file=sys.stderr)
    if args.json:
        print(json.dumps(panel, indent=2))
    return 0 if pv == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
