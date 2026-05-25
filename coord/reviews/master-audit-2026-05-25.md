# Master audit — xaxiu-harness session 2026-05-24 → 2026-05-25

**Audit type**: end-of-session strategic review
**Author**: Claude (in-session, 1M context window)
**Scope**: where the project IS, where it CAN be, what closes the gap
**Honesty note**: this is my synthesis without external engine cross-check;
operator can run `harness review coord/reviews/master-audit-2026-05-25.md
--lens-set doc-review` to challenge it via the SDK we just shipped.

---

## 1. Where we are right now (concrete state)

### Shipped this session (chronological)

| # | Commit | Ship |
|---|---|---|
| 1 | `4da95ee` | W11-PYTHON-SDK-API-IMPL — final Wave 11 row (the SDK gate) |
| 2 | `8d7043c` | W5-E E2E success-path proof, retiring Wave 5 |
| 3 | `f4c64b3` | Wave 11 closeout narrative |
| 4 | `dd4ca93` | SESSION-2026-05-24-CLOSEOUT row |
| 5 | `8bf5ba9` | **W11-SDK-E2E-LIVE-ENGINE-PROOF** — first real-engine validation (caught + fixed adapter auto-bootstrap bug) |
| 6 | `7e6a16c` | 20-agent operator-review panel Round 1 (18/19 WAIT-FOR-WAVE-12) |
| 7 | `60ecfcf` | **W12-A operator-blocker triage** (5 fixes for the 3 universal panel blockers) |
| 8 | `7a886c5` | Round 2 panel: 13/15 effective APPROVE-AND-SHIP |
| 9 | `fbf31e8` | W12-A STATUS.csv follow-up |
| 10 | `578c2cd` | v1.0.0-rc.1 24h autonomous run armed |
| 11 | `feeb446` | W12-B max-tokens backlog + Aquinas student review |
| 12 | `46a2289` | **`harness review` CLI + dashboard cost/L5 widgets** (the combo ship) |

**12 commits, ~7 hours, $0.20 / $5 budget consumed.**

### State at this moment

| Signal | Value |
|---|---|
| Tag | `v1.0.0-rc.1` pushed to remote |
| Tests | **2179+** green (no regressions across all 12 commits) |
| Production todos for Claude | **0** (V1.0.0-RC1-AUTONOMOUS-RUN is for operator review) |
| Panel approval rate | 87% (13/15 substantive votes APPROVE-AND-SHIP Round 2) |
| 24h autonomous test | armed (~7h in of 24h) |
| Observer | armed, watchdog OK, cron firing hourly |
| Cost spent today | $0.20 of $5 budget (4%) |
| Real-world track record | 1 client review shipped (Aquinas student PDF) via `harness review` |

### What the harness can actually do right now

1. **Python SDK** with context-frugal returns + lazy fetch (proven against 3 real engines)
2. **CLI verbs**: `dispatch`, `retrieve`, `cost-today`, `today`, `preflight`, `preflight-latency`, `agent init`, `observer arm/restart/watchdog-status`, `coord plan/run/integrate`, **`review <file>`**, more
3. **Cross-platform observer** with self-recovery + L5 escalation
4. **Live dashboard** at localhost:8765 with cost widget + L5 banner pinned top
5. **Multi-engine review** of any PDF/MD/TXT/source-file via `harness review`
6. **Auto-bootstrap default adapter** so first-call works on a fresh clone
7. **24h autonomous test cycle** (cron-armed observer + watchdog + daily retro)

---

## 2. Where we can be (three horizons)

### Horizon A — 1 month out (Wave 12-13)

**Target state**: tagged v1.0.0 final, README + landing page that a non-Claude
agent can land on and start using, 5-10 real-world reviews under our belt,
mypy-strict CI gate, morning email brief.

**Concrete delta**:
- Wave 12-B backlog burned down (~6 rows, ~12-15h total)
- 5-10 real client-work reviews done via `harness review` (validates the
  workflow under real pressure)
- README rewritten with the live screenshots + the SDK quickstart
- v1.0.0 tag promoted from RC
- Public GitHub repo polish (issue templates, contribution guide, license
  file if missing)

**What "we are there" looks like**: another developer can `git clone +
pip install -e . + set API keys + harness review some-doc.pdf` and get
real value within 5 minutes.

### Horizon B — 3 months out

**Target state**: PyPI listing, IDE extension (VSCode minimum), 10-50
active users beyond the operator, a small Discord/discussion presence,
comparative content (vs Aider/Cursor/Claude Code) drawing search traffic.

**Concrete delta**:
- PyPI: `pip install xaxiu-harness` (probably needs the package rename
  question answered — what's the public name?)
- VSCode extension: command palette → "harness: dispatch" + "harness: review
  current file" + "harness: cost today"
- Landing page (single-page, screenshots, 30-second demo video, install
  command above the fold)
- Blog post + HN/Reddit submission ("the SDK lets agents offload work to
  subscription engines without burning their context window")
- Discord or GitHub Discussions for user questions
- 2-3 case studies from real usage (could be the operator's own student-
  review workflow, anonymized)

**What "we are there" looks like**: someone who's never met the operator
finds the harness via Google or a tweet, installs it, uses it for a week,
and stays.

### Horizon C — 6-12 months out

**Target state**: real users, real revenue (if pursued commercially) or
real adoption (if pursued OSS-first), plugin system for custom engine
adapters, optional hosted version for non-technical operators, marketplace
listings (VSCode + JetBrains).

**Concrete delta**:
- Plugin architecture for engine adapters (so users can add Mistral,
  Llama, etc.)
- Hosted offering (so non-technical operators don't need a clone) — or
  explicit decision to stay self-hosted
- VSCode Marketplace listing (10K+ installs realistic for tools in this
  category in year 1)
- Multi-user / org features (shared cost ledger, team budget caps,
  per-user audit trail)
- Comparative positioning that's holding ground (search ranks for
  "multi-engine LLM SDK", "agent context window optimization")

**What "we are there" looks like**: the project has its own life beyond
the operator — outside contributors, user-reported issues, integration
asks from other tools.

---

## 3. The gap (what closes each horizon)

### To reach Horizon A (1 month, ~25-40h of work)

| Move | Effort | Why |
|---|---|---|
| Burn Wave 12-B backlog (6 rows) | 12-15h | morning email, mypy gate, live engine smoke, dashboard L5 HTML, etc. All scoped + named. |
| 5-10 real reviews via `harness review` | 5h (10x ~30min) | Validates the workflow + finds edge cases + builds a case-study library |
| README rewrite + landing page draft | 4-6h | Currently README is engineering-focused; need a "you can use this" framing |
| `pip install -e .` smoke + setup.py polish | 2-3h | The AGENT_QUICKSTART claims pip install works; verify on a fresh clone |
| v1.0.0 final tag + GitHub release notes | 2h | Promote from RC |
| Optional: short demo video (60-90s) | 2-3h | Recording + voiceover; embeds on landing page |

**The single hardest unknown**: whether `pip install -e .` actually works
end-to-end on a clean machine. We've never tested this — every dispatch
in this session was `PYTHONPATH=src python -m harness`. If pip install
breaks, the AGENT_QUICKSTART promise breaks.

### To reach Horizon B (3 months, ~120-200h)

| Move | Effort | Why |
|---|---|---|
| All of Horizon A | 25-40h | Prerequisite |
| PyPI publish (rename research + first publish) | 4-8h | Includes deciding the public package name + obtaining ownership on PyPI |
| VSCode extension (minimum: 3 commands) | 30-50h | Real engineering investment; TypeScript + extension lifecycle |
| Landing page (static site + 2-3 demo videos) | 15-25h | Design + writing + recording |
| Blog post + HN submission + measure | 5-10h | The narrative + distribution moment |
| 2-3 case studies written up | 5-10h | Each one is a ~2000-word post with screenshots |
| Discord setup + initial moderation | 5-10h | First 50 users need a place to ask questions |

**The single hardest unknown**: distribution. Engineering effort here is
maybe 60% of the total; the rest is "does the narrative resonate". If the
blog post lands at 0 upvotes on HN, the 3-month plan needs a hard rethink.

### To reach Horizon C (6-12 months, ~600-1000h)

| Move | Effort | Why |
|---|---|---|
| All of Horizon B | 120-200h | Prerequisite |
| Plugin architecture for engine adapters | 60-100h | Real refactor; backward-compatible engine ABI |
| Hosted offering (if pursued) | 100-200h | SaaS infrastructure; auth; billing; SLA |
| VSCode Marketplace polish + JetBrains port | 80-120h | Two extensions in production |
| Multi-user / org features | 60-100h | Shared ledger, RBAC, team budget caps |
| Real engineering maintenance for outside users | ~10h/week | Issues, PRs, support, breaking change management |
| Open-source-vs-commercial decision + execution | varies | This is THE business question |

**The single hardest unknown**: whether the project is fundamentally a
*product* (someone pays for it) or a *tool* (open-source, gets adopted,
no revenue). That decision affects every other choice in this horizon.

---

## 4. What could kill this (risks)

### High-probability, recoverable

- **Operator burnout** — this session has been 12 commits in 7 hours.
  Real-day-of-use proves nothing if the operator isn't around. Mitigation:
  the 24h autonomous test is exactly this concern operationalized; if it
  passes overnight, the operator's presence isn't required for continuity.

- **`pip install -e .` doesn't actually work** — every command we ran
  used `PYTHONPATH=src python -m harness`. The AGENT_QUICKSTART claims
  `pip install -e .` works. We never verified. Easy to test, easy to fix,
  but a real risk to the "fresh clone agent" promise.

- **Engine API surface changes** — Kimi/DeepSeek/MiMo wrappers depend on
  current API shapes. Circuit breakers + cooldowns help, but adaptive
  wrappers don't exist. Mitigation: write a once-a-week CI smoke that
  fires one real call per engine.

### Medium-probability, harder to recover

- **A real-world failure that loses someone's data** — currently low risk
  because everything writes to local disk in the user's repo. Becomes a
  real risk if a hosted offering or shared-org-ledger feature ships.

- **Anthropic / OpenAI launching multi-engine routing** — unlikely
  because they want lock-in, but not impossible. Mitigation: our
  differentiator is *agent-context-window economics*, which they
  structurally can't optimize for the same way.

- **Discovery that nobody wants this** — the value prop ("agents offload
  work without burning their context") is real but unvalidated outside
  the operator. The first 10 external users will tell us whether the
  framing resonates. Mitigation: actually publish + actually measure.

### Low-probability, catastrophic

- **A security incident in the FastAPI dashboard** — currently the
  dashboard is localhost-bound, which is safe. Becomes catastrophic if
  it ever ships exposed to the public internet without auth. Mitigation:
  keep the dashboard explicitly localhost; add auth before any networked
  variant ships.

- **Engine cost spike** — the $5/session cap protects against runaway
  spend; the multi-engine fallback protects against single-engine
  dependency. Compound failure (cap broken + fallback skipped) would be
  expensive but visible. Mitigation: the cap is enforced in code +
  documented + the L5 banner fires when exceeded.

---

## 5. Recommended sequencing (the actual answer)

If I had to give the operator ONE thing to do next, it's:

> **Tomorrow morning: run `bash scripts/v1-rc1-24h-report.sh`. If preflight
> is PASS-WITH-WARNINGS or PASS, and zero L5 escalations fired overnight,
> promote v1.0.0-rc.1 to v1.0.0 final. Then test `pip install -e .` on a
> fresh shell to verify the AGENT_QUICKSTART promise.**

That single action validates the 24h-survival claim AND closes the
biggest unverified risk (the install path).

If the operator wants 1-2 weeks of focused work that meaningfully advances
the project, the priority ordering is:

1. **Use `harness review` on 5-10 real documents** (5h, immediate validation)
2. **Fix `pip install -e .`** if it's broken; document the install path that works (2-3h)
3. **Burn down 3-4 Wave 12-B rows** (mypy gate, morning email, live-engine smoke, dashboard L5 HTML) — pick by what touches your day-to-day pain (8-10h)
4. **Rewrite README around the `harness review` use case** — the most concrete value-prop we have (2-4h)
5. **Tag v1.0.0 final** when README is solid + tests are green + at least one new external user has tried it (1h)

This is ~20-25h of focused work, gets you to "v1.0.0 final + ready for
public release post" in 2 weeks of part-time effort.

If the operator wants to spend 1 night doing the most-fun thing:

> **`harness review` whatever real document is on their desk right now.**
> Then if there's more energy, `harness review src/harness/_sdk.py
> --lens-set code-review` for fun self-audit.

---

## 6. Honest meta-observations

1. **The session arc was unusually clean.** Wave 11 closeout → real E2E
   discovers bug → fix → 20-agent panel → 3 universal blockers → Wave
   12-A fixes blockers → Round 2 approves → v1.0 RC → real client task
   → bottle the workflow as a CLI verb. Each step naturally led to the
   next. This is uncommon and worth noting because it usually means the
   ground-truth design is correct; the foundation is sound.

2. **The harness used itself for its own planning AND its own bug-finding.**
   The 3-engine planning panel (commit feeb446) chose what to ship.
   The 20-agent operator-review panel (commits 7e6a16c + 7a886c5) found
   the bugs that became Wave 12-A. The Aquinas review (commit feeb446)
   was bottled as `harness review` (commit 46a2289). This is the
   ouroboros pattern: tool used to improve itself. It's a signal the
   primitives are useful, not just present.

3. **Cost discipline is real.** $0.20 spent across 12 commits, 4+ panel
   dispatches, 1 real client review, dozens of single-engine probes.
   The "subscription engines cost $0" property isn't just a slogan —
   it shapes the usage pattern. The harness has a cost arithmetic that
   actually favors heavy use.

4. **The non-technical-operator UX still gates the bigger horizons.**
   Everything that shipped is CLI-grade or agent-grade. A 100% non-
   technical operator (true ChatGPT-tier expectation) still needs:
   installer, GUI, hosted version. That's Horizon C work and probably
   needs a business decision before it gets investment.

5. **The 24h autonomous test is the load-bearing claim that hasn't
   resolved yet.** Everything else has at least one proof point. The
   "harness can run unattended" claim resolves only when tomorrow's
   `v1-rc1-24h-report.sh` produces a clean output. That's the genuine
   single point of remaining uncertainty.

---

## 7. One-sentence verdict

The harness is at v1.0.0-rc.1 with a panel-approved feature set + a
proven SDK + a real-client review workflow shipped as a CLI verb; the
gap to v1.0.0 final is 1-2 weeks of part-time polish (Wave 12-B
burndown + install-path verification + README rewrite + one external
user); the gap to a publicly-discoverable project that has its own
adoption is 2-3 months of focused work on distribution (PyPI + landing
page + VSCode extension + narrative); the gap to a tool with its own
ecosystem is 6-12 months and a business-model decision.

What kills it isn't engineering — it's whether anyone else discovers
+ stays. That's solvable, but solving it means investing time in
distribution work the current trajectory has not yet started.
