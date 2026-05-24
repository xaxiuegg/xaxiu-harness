"""W10 operator-UX thinking panel — 8 MiMo personas brainstorming what
would let a non-technical operator (ChatGPT/Claude-Code-tier user)
actually use the harness without engineering support.

Operator directive 2026-05-25 (mid-W10): the W9 readiness panel
returned 0/10 YES.  My honest rating for a ChatGPT-tier user is
2/10.  The gap is huge.  This panel thinks through the design
space — not "what should W10 ship" (that's already queued) but
"what would actually move the rating from 2/10 to 7+/10".

Each persona thinks from a distinct lens.  Output: convergent
themes + concrete UX recommendations + Wave 11+ candidates.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "operator-ux-panel"


# (engine, model, persona_id, persona_lens)
PERSONAS: list[tuple[str, str, str, str]] = [
    ("mimo", "mimo-v2.5-pro", "U1-newbie-clone",
     "FIRST-CLONE NEWBIE.  Imagine a non-technical operator (thinks "
     "of LLM tools like ChatGPT — type, get answer) who just cloned "
     "the repo and double-clicked something.  Trace their first 30 "
     "minutes step-by-step.  Where do they hit a wall?  What ONE "
     "UX change would unblock the most operators?"),
    ("mimo", "mimo-v2.5-pro", "U2-installer-design",
     "INSTALLER DESIGNER.  Sketch what a non-Python installer "
     "should look like: bundled python? PyInstaller exe? .msi? "
     "Brew/winget?  What about API-key population (KIMI_API_KEY, "
     "DEEPSEEK_API_KEY, MIMO_API_KEY, DPAPI seed)?  Design the "
     "first-run wizard end-to-end."),
    ("mimo", "mimo-v2.5-pro", "U3-cli-vs-gui",
     "CLI-VS-GUI DESIGNER.  The current harness exposes 30+ CLI "
     "verbs.  Is a CLI the right surface for a non-technical "
     "operator at all?  Sketch the minimal GUI: tray icon? "
     "Electron app?  Web dashboard as the primary surface (not "
     "an opt-in)?  What stays CLI for power users and what becomes "
     "GUI-default?"),
    ("mimo", "mimo-v2.5-pro", "U4-error-recovery",
     "ERROR RECOVERY DESIGNER.  When something breaks (engine "
     "quarantined, observer hung, audit STOPped, secret leaked) "
     "today the operator reads CLI output and pattern-matches to "
     "fix commands.  Design the recovery UX: one-click fixes? "
     "Wizards?  Auto-recovery with operator notification?  What's "
     "the MVP that prevents the operator from needing engineering?"),
    ("mimo", "mimo-v2.5-pro", "U5-cost-visibility",
     "COST VISIBILITY DESIGNER.  Non-technical operators expect "
     "to know 'how much did this session cost?' without grepping "
     "ledgers.  Design the cost surface: dashboard widget?  Daily "
     "email?  Per-dispatch live counter?  How do you make the "
     "tp- (subscription) vs sk- (per-token) cost model obvious "
     "without lecturing?"),
    ("mimo", "mimo-v2.5-pro", "U6-trust-calibration",
     "TRUST CALIBRATION DESIGNER.  The operator must trust the "
     "autonomous loop to run unsupervised.  Today the L5-only "
     "escalation contract is the trust seam, but the operator "
     "can't verify it.  Design trust signals: progress visualizations? "
     "Heartbeat dashboard?  'What did the harness do today' in "
     "plain English?  How would a non-technical operator know if "
     "the loop is doing useful work vs. burning money idly?"),
    ("mimo", "mimo-v2.5-pro", "U7-onboarding-content",
     "ONBOARDING CONTENT DESIGNER.  Forget the technical docs.  "
     "Design a 5-minute video script + 1-page printable cheat "
     "sheet + 3-screen onboarding tour that a 65-year-old "
     "professional (no Python, no git, no terminal habit) could "
     "follow.  What's the absolute MINIMUM operator-facing surface "
     "you reveal vs. hide behind 'advanced'?"),
    ("mimo", "mimo-v2.5-pro", "U8-pragmatic-roadmap",
     "PRAGMATIC PRODUCT MANAGER.  Synthesize the realistic path "
     "from current 2/10 (non-tech) -> 7/10 over 3-6 months of "
     "Wn waves.  Sequence the work: what's Wave 11 (highest-leverage "
     "UX), Wave 12 (next), Wave 13 (next)?  Be ruthless about "
     "cuts — what features should be DROPPED to simplify the "
     "operator surface?"),
]


# State snapshot for each persona
def _gather_snapshot() -> str:
    snapshot: list[str] = []
    # CLI verb list
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness", "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        snapshot.append("## CLI verbs (`harness --help`)\n\n```\n"
                        + (proc.stdout[:3000] or proc.stderr[:1500])
                        + "\n```\n")
    except Exception as exc:
        snapshot.append(f"## CLI verbs — FAILED: {exc}\n")

    # Operator runbook
    try:
        runbook = (REPO_ROOT / "docs" / "OPERATOR_RUNBOOK.md").read_text(
            encoding="utf-8",
        )
        snapshot.append("## OPERATOR_RUNBOOK.md\n\n"
                        f"```markdown\n{runbook[:4500]}\n```\n")
    except OSError:
        snapshot.append("## OPERATOR_RUNBOOK.md — not found\n")

    # W9 readiness panel synthesis
    try:
        synth = (REPO_ROOT / "coord" / "reviews" / "readiness-panel"
                 / "SYNTHESIS.md").read_text(encoding="utf-8")
        snapshot.append("## W9 readiness panel verdict\n\n"
                        f"```markdown\n{synth[:3500]}\n```\n")
    except OSError:
        snapshot.append("## W9 readiness panel — not found\n")

    # Operator profile
    snapshot.append("""\
## Operator profile (memory: user_non_technical_role)

The operator is NON-TECHNICAL.  Can:
  - Edit YAML, run CLI commands, manage Windows Task Scheduler
  - Read STATUS.csv

Cannot:
  - Author Python
  - Debug tracebacks
  - Read engine logs and root-cause issues

User-stated framing (2026-05-25): treats LLM tools like
ChatGPT/Claude Code (type, get answer).  Honest rating today
for that user profile: 2/10.

Wave 10 already queued (operator-readiness UX):
  W10-PREFLIGHT-EXIT-CODE-SEMANTICS, W10-DAILY-QUICKSTART-VERB,
  W10-ENV-VAR-WIZARD, W10-STATUS-CSV-OVERWHELM,
  W10-PREFLIGHT-REMEDIATION-CARDS, W10-PROFILE-AWARE-DEFAULTS,
  W10-DPAPI-SEEDING-VISIBILITY, plus 3 infrastructure rows.

Question: what would actually move 2/10 -> 7/10?  Not just W10
polish — the structural UX changes.
""")
    return "\n".join(snapshot)


_INSTRUCTIONS = """\
You are one of 8 operator-UX thinking-panel reviewers.  Use the
state snapshot + your assigned lens to answer:

## Rubric

For each, give a concrete recommendation (not "improve UX" — what
specifically?):

1. **Top 3 changes** that would move the non-technical operator
   rating from 2/10 to 7/10.  Ranked by leverage.

2. **One Wave 11 candidate row** (format: `W11-<KEBAB-NAME>`) with
   1-paragraph acceptance criteria.

3. **One feature to KILL or HIDE** — what current harness surface
   should disappear (or move behind `--advanced`) to simplify the
   operator's experience?

4. **The minimum viable first-run path**: list the literal commands
   / clicks / inputs a fresh-clone operator must execute to reach
   "the harness is now usefully running and I trust it".  Goal: ≤5
   steps for the chat-tier user.

5. **Trust seam**: name the one trust signal a non-technical
   operator would actually believe.

Keep your response focused — under 600 words.  No preamble.

Your lens:
"""


def _run_one(engine_name: str, model: str, pid: str, lens: str,
             snapshot: str) -> tuple[str, str, str]:
    started = time.monotonic()
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return (pid, f"engine init failed: {exc}", "FAIL")
    prompt = (
        snapshot
        + "\n\n---\n\n"
        + _INSTRUCTIONS
        + lens
    )
    resp = eng.dispatch(prompt, model, {"max_tokens": 4000})
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return (pid, f"engine failed: {resp.error}", "FAIL")
    return (pid, resp.text.strip(), f"OK ({elapsed_ms}ms)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[operator-ux] gathering state snapshot...", file=sys.stderr)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[operator-ux] snapshot: {len(snapshot)} chars", file=sys.stderr)

    print(f"[operator-ux] dispatching {len(PERSONAS)} reviewers "
          f"(max_workers=8)...", file=sys.stderr)
    started = time.monotonic()
    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_run_one, eng, model, pid, lens, snapshot): pid
            for eng, model, pid, lens in PERSONAS
        }
        for f in as_completed(futures):
            pid, text, status = f.result()
            results[pid] = (text, status)
            text_len = len(text)
            print(f"  [{status}] {pid:<28} text_len={text_len}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started
    print(f"\n[operator-ux] elapsed {elapsed_s:.0f}s", file=sys.stderr)

    # Per-persona files
    for pid, (text, status) in results.items():
        (OUT_DIR / f"{pid}.md").write_text(
            f"<!-- persona={pid} status={status} -->\n\n# {pid}\n\n{text}\n",
            encoding="utf-8",
        )

    # Synthesis
    synth_lines = [
        "# Operator-UX thinking panel — synthesis",
        "",
        f"_Dispatched: {len(PERSONAS)} MiMo personas, elapsed {elapsed_s:.0f}s_",
        "",
        f"State snapshot fed to each reviewer is at `_state_snapshot.md`.",
        "",
    ]
    for eng, model, pid, lens in PERSONAS:
        text, status = results.get(pid, ("(no response)", "MISSING"))
        synth_lines.append(f"## {pid}\n\n{text}\n\n---\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synth_lines), encoding="utf-8",
    )
    print(f"[operator-ux] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
