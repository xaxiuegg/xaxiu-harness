"""Validation panel — 5 agents thinking through whether the harness's
natural target user is an AGENTIC CODING AGENT (Claude Code, ChatGPT
with code interpreter, Cursor, Aider, etc.) cloning the repo and
using it on a fresh project, rather than the non-technical
chat-tier user.

Operator hypothesis 2026-05-25: non-tech user can't use it; but an
agent can read CLAUDE.md, parse tracebacks, run --help, write
STATUS.csv, and dispatch — saving 20-40 hours of scaffolding per
fresh project.

Each persona thinks from a distinct lens:
  A1 — fresh-clone walkthrough: what literally happens?
  A2 — adapter design: how good is the project-adapter onboarding?
  A3 — competing-tools: vs Cursor rules / Aider conventions / Claude
       Code skills / LangGraph templates — what does the harness offer
       that the agent can't get easier elsewhere?
  A4 — friction inventory: what BREAKS for an agent even though it
       wouldn't break for a human dev?
  A5 — W11+ reframe: if "agent-as-user" is the target, what does
       Wave 11 look like differently?
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

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "agent-as-user-panel"


PERSONAS: list[tuple[str, str, str, str]] = [
    ("deepseek", "deepseek-v4-flash", "A1-fresh-clone-walkthrough",
     "FRESH-CLONE WALKTHROUGH.  Imagine a Claude Code session in a "
     "BRAND-NEW project (say, a Python web scraper).  The operator "
     "types: 'clone xaxiu-harness and use it to add multi-engine "
     "dispatch + audit to this scraper'.  Trace the agent's first 30 "
     "minutes step-by-step.  Where does the agent succeed?  Where "
     "does it hit a wall a human dev wouldn't?  Be specific with "
     "literal commands the agent would issue."),
    ("deepseek", "deepseek-v4-flash", "A2-adapter-onboarding",
     "ADAPTER DESIGN REVIEWER.  `harness adapter from-description` "
     "generates a YAML adapter from natural-language project "
     "description.  For an agent cloning the harness into a fresh "
     "project, evaluate this onboarding path.  Is the adapter format "
     "self-explanatory from the YAML schema + a sample?  Does the "
     "generation actually produce a usable adapter from a 1-paragraph "
     "description?  What's the simplest 'works on my new project' "
     "path?"),
    ("mimo", "mimo-v2.5-pro", "A3-competing-tools",
     "COMPETING-TOOLS BENCHMARK.  Agentic coding agents already have "
     "options: (a) Cursor's .cursorrules, (b) Aider's CONVENTIONS.md + "
     "model config, (c) Claude Code's plugins + skills + memory, "
     "(d) LangGraph templates, (e) just writing engine routing from "
     "scratch with `requests`/`httpx`.  What does the harness offer "
     "that the agent cannot get easier elsewhere?  Is the unique "
     "value (audit gate + mutation canary + proxy circuit + STATUS "
     "tracking + observer cycle) worth the clone + install + adapter "
     "step?  Honestly: would YOU (as an agent) recommend operator "
     "clone it for a new project, or build minimal scaffolding in "
     "their repo directly?"),
    ("deepseek", "deepseek-v4-flash", "A4-friction-inventory",
     "FRICTION INVENTORY.  List every concrete friction point a "
     "Claude Code / Cursor / Aider session would hit when cloning "
     "the harness onto a fresh project and trying to be productive "
     "in the first hour.  Include: (1) Windows-only DPAPI (Mac/Linux "
     "agent?), (2) the 30-verb CLI surface, (3) coord v2 vs adapter, "
     "(4) STATUS.csv ownership (harness's own vs project's), (5) "
     "memory file pattern needing to be set up, (6) anything else.  "
     "For each: is it real friction or just 'agent needs to read 2 "
     "more docs'?"),
    ("mimo", "mimo-v2.5-pro", "A5-w11-reframe",
     "W11-REFRAME ARCHITECT.  IF the target user pivots from "
     "'non-technical chat-tier user' to 'agentic coding agent "
     "cloning the repo for a fresh project', what does Wave 11 "
     "look like differently?  Specifically: (a) what currently-queued "
     "W11 rows become LESS important (installer? GUI? morning email?), "
     "(b) what NEW W11 rows surface (better adapter UX, smaller CLAUDE.md "
     "template, agent-friendly docs, cross-platform DPAPI alternative, "
     "etc.), (c) does the wave count to a credible 'agents love this' "
     "rating drop from 6 to 2-3?  Be concrete."),
]


def _gather_snapshot() -> str:
    """Snapshot what a fresh agent would actually see."""
    snapshot: list[str] = []
    # CLAUDE.md top
    try:
        claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        snapshot.append("## CLAUDE.md (top 3000 chars; what agent reads first)\n\n"
                        f"```markdown\n{claude_md[:3000]}\n```\n")
    except OSError:
        pass

    # Adapter sample
    try:
        # Find any adapter YAML
        adapters = list(REPO_ROOT.glob("spec/samples/*.yaml"))
        if adapters:
            adapter_text = adapters[0].read_text(encoding="utf-8")
            snapshot.append(f"## Sample adapter ({adapters[0].name})\n\n"
                            f"```yaml\n{adapter_text[:2000]}\n```\n")
    except OSError:
        pass

    # CLI top
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness", "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        snapshot.append("## harness --help\n\n```\n"
                        + (proc.stdout[:2500] or proc.stderr[:1500])
                        + "\n```\n")
    except Exception as exc:
        snapshot.append(f"## CLI --help failed: {exc}\n")

    # The hypothesis being tested
    snapshot.append("""\
## The pivot hypothesis (post-W10)

The non-technical chat-tier user fails at the first-run wall (2/10).
The CLI-literate user is at 6/10 (usable with runbook).  But the
THIRD user profile — an AGENTIC CODING AGENT cloning the harness
into a fresh project — may be the natural fit:

- Agent solves install / env-var / DPAPI friction in 2-3 tool calls
- Agent reads CLAUDE.md + dispatch-rules.md + memory files natively
- Agent uses STATUS.csv + audit gate + canary as scaffolding it
  doesn't have to re-implement
- Agent dispatches via xaxiu-swarm with full understanding of
  fallback chains

Per-new-project savings estimate (from observed harness build cost):
  - Engine routing: 4-8h
  - Audit gate: 3-6h
  - Task tracking (STATUS.csv): 2-4h
  - Cost ledger: 1-3h
  - Observer cycle: 4-8h
  - Mutation canary: 3-6h
  - Hooks / safety rails: 2-4h
  Total: 20-40h of scaffolding per fresh project

Test if this hypothesis holds.  Be skeptical.

## Operator framing (verbatim)

'if a non-technical user can not use the harness confidently, would
an agentic coding agent like claude or chatgpt would be able to run
it effectively. Like cloning a git repo down, and use the harness
rightaway. This replaced significantly the time of setting up all
the rules, agents, and establish the structures we need like status
csv agents routings etc'
""")
    return "\n".join(snapshot)


_INSTRUCTIONS = """\
You are one of 5 validation-panel reviewers.  Use the state snapshot
+ your assigned lens to answer:

## Output structure (mandatory; keep under 600 words)

1. **Headline verdict** — one sentence: is the agentic coding agent
   the natural target user for the harness?  YES / YES-IF / NO /
   NEEDS-PIVOT.

2. **Strongest evidence FOR the hypothesis** — what specifically
   about the harness's design suits an agent's working style?

3. **Strongest evidence AGAINST** — what would frustrate an agent
   that wouldn't frustrate a human dev?

4. **The 3 most important W11 changes** to optimize for "agent
   clones + uses on fresh project" as the primary use case.

5. **Single-sentence recommendation** — pivot / dual-target /
   no-pivot.

No preamble.  No restating the snapshot.  Your lens:
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
    resp = eng.dispatch(prompt, model, {"max_tokens": 4500})
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return (pid, f"engine failed: {resp.error}", "FAIL")
    return (pid, resp.text.strip(), f"OK ({elapsed_ms}ms)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[agent-panel] gathering state snapshot...", file=sys.stderr)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[agent-panel] snapshot: {len(snapshot)} chars", file=sys.stderr)

    print(f"[agent-panel] dispatching {len(PERSONAS)} reviewers...",
          file=sys.stderr)
    started = time.monotonic()
    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_run_one, eng, model, pid, lens, snapshot): pid
            for eng, model, pid, lens in PERSONAS
        }
        for f in as_completed(futures):
            pid, text, status = f.result()
            results[pid] = (text, status)
            text_len = len(text)
            print(f"  [{status}] {pid:<32} text_len={text_len}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started
    print(f"\n[agent-panel] elapsed {elapsed_s:.0f}s", file=sys.stderr)

    for pid, (text, status) in results.items():
        (OUT_DIR / f"{pid}.md").write_text(
            f"<!-- persona={pid} status={status} -->\n\n# {pid}\n\n{text}\n",
            encoding="utf-8",
        )
    synth_lines = [
        "# Agent-as-natural-user validation panel — synthesis",
        "",
        f"_Dispatched: {len(PERSONAS)} reviewers, elapsed {elapsed_s:.0f}s_",
        "",
    ]
    for eng, model, pid, lens in PERSONAS:
        text, status = results.get(pid, ("(no response)", "MISSING"))
        synth_lines.append(f"## {pid}  ({eng}/{model})\n\n{text}\n\n---\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synth_lines), encoding="utf-8",
    )
    print(f"[agent-panel] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
