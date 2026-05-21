# Packet: README.md for v0.4.1 — operator-facing entry point

## Mission

There is no `README.md` at the repo root. New operators (or future-Claude in a fresh session) opening the repo on GitHub have no entry-point summary. Write a focused README — operator-readable, not exhaustive — that answers "what is this, how do I run it, what do the 22 CLI verbs do."

Target audience: non-technical operator (memory `user_non_technical_role`). Plain English, no code-jargon walls of text.

## In-scope NEW files

- `README.md` (repo root)

## In-scope MODIFY files

NONE.

## Required sections (in order)

1. **Title + one-line tagline**: "xaxiu-harness — cross-project multi-engine LLM dispatch + autonomous loop, v0.4.1"

2. **What is this?** — 3 sentences. Mention: dispatches packets to Kimi/DeepSeek/Anthropic/Gemini; tracks state in `coord/STATUS.csv`; runs autonomously via Task Scheduler.

3. **Quick start** — three numbered commands:
   ```
   git clone <repo>
   cd xaxiu-harness && python -m venv .venv && .venv\Scripts\activate && pip install -e .
   harness init -p my-first-project -t solo-dev
   ```

4. **The 22 CLI verbs at a glance** — markdown table with three columns: Group | Subcommands | What it does. Include status / observer / loop / coord / heartbeat / state / session / adapter / budget / proxy / dispatch / engines / env / init / install / replay / dashboard-serve / burst / lock / priority / retro / loops. One short row each.

5. **The autonomous loop** — explain the three Task Scheduler entries (LoopTick / ObserverCycle / DailyRetro) and what each does. Mention that `harness loop start --cadence-minutes 30` arms them.

6. **The session-handoff monitor** — one paragraph. `harness session check` reports SOFT/STRONGLY/CRITICAL based on Claude Code transcript jsonl size (8/18/35 MB thresholds, calibrated from operator's historic crash at 52 MB). Heavy = rotate at next checkpoint; SOFT = informational only.

7. **v2 architecture (planner/worker pattern)** — link to `spec/multi-agent-harness-architecture.md`. One paragraph: 24-slot parallel coordinator with isolated git worktrees and JSON-based handoffs. Status: shipped, awaiting first end-to-end run.

8. **Project structure** — terse tree showing `src/harness/`, `spec/`, `coord/`, `tests/`, `adapters/`, `.harness/` (runtime).

9. **Memory + multi-session scoping** — one paragraph explaining that this repo expects to live alongside warehouse and other projects, and how `feedback_multi_session_scoping` keeps them isolated.

10. **License / contributing** — placeholder: "MIT (see LICENSE)". No LICENSE file required this packet; just the line.

## Style requirements

- Operator profile: non_technical preferred. No "monad", "covariance", "metaclass", etc.
- Bullet-and-table heavy; minimal walls of prose.
- Each section ≤200 words. Whole README ≤700 lines.
- Markdown links to existing spec/* files where relevant.
- Show 2-3 verb examples but don't try to document everything — point at `harness <verb> --help`.

## Acceptance criteria

1. `README.md` exists at repo root.
2. All 22 CLI verb groups listed in the table.
3. Quick-start works on a fresh Windows clone (manual verification by operator post-merge).
4. `python -m pytest tests/ -q` still green (no test impact expected).
5. Single commit: `doc(readme): v0.4.1 operator-facing entry point`.

## Reference

- CLAUDE.md (project state table; mirror its terminology)
- spec/multi-agent-harness-architecture.md (v2 design)
- spec/session-handoff-monitor.md (session-handoff feature)
- spec/operator-modes.md (operator config surface)
- Memory `user_non_technical_role` (style baseline)

## Output format

1 new file at repo root + 1 commit. ≤700 lines.
