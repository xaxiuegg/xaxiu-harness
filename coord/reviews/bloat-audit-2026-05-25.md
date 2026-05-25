# Harness Bloat + Hallucination Risk Audit + Operator→SDK Shift Map

**Date**: 2026-05-25
**Trigger**: operator question 2026-05-25:
  - "evaluate the risk of bloating and overwhelming the agent/operator
    with all the features we add..."
  - "is there anything on the operator side that we can shift to sdk
    agent to reduce risk"

**Author**: Claude (in-session)
**Status**: opinion piece — needs cross-engine validation before
  any action.  Operator directive: dispatch 15-engine panel for
  strategic plan.

---

## Part 1: Bloat audit — two audiences, two answers

### Audience A: agent calling `harness.dispatch()` (the design target)

- The SDK surface is **3 public functions** (`dispatch`, `retrieve`,
  `budget_status`) plus `DispatchResult` with a lazy `.full()`.
- **~36 tokens per dispatch** is the measured per-call cost (W11_E2E_SDK_PROOF).
- Everything else (observer cycles, watchdog, cost ledger, dispatch cache,
  engine cooldowns, circuit breakers, L5 flagging, preflight gates,
  backups) runs in the background and never touches the agent's context.

**Bloat risk: LOW.**  As long as new features stay in this
background-automation pattern, the SDK-calling agent doesn't notice them.

### Audience B: operator / dev-Claude doing operations (you + me)

What the operator-side has to know:
- 30+ CLI verbs + their flags
- 4+ memory entries to load at session start
- The STATUS.csv schema + status vocabulary
- The wave-plan structure
- The runbook's 10 sections + 3 appendices
- Where every artifact lives (`coord/reviews/`, `coord/coverage/`,
  `coord/observer/`, `spec/`, `docs/`)
- Which commands exist NOW vs which are planned

**Bloat risk: MEDIUM and growing.**  Every new CLI verb is real
cognitive cost.  Every new doc is a doc to read.  Every new STATUS.csv
row is a row to track.

## Part 2: Hallucination risk vectors observed THIS SESSION

1. **Future-as-present in docs** — runbook describes
   `harness secrets rotate kimi` (doesn't exist).  DeepSeek's cross-engine
   review of the Horizon C plan flagged this exact issue.  Future-Claude
   would try it + fail + waste a cycle.

2. **Lens-set names** — three valid (`default`, `code-review`,
   `doc-review`).  Claude could easily invent `security-review`,
   `prose-review`, `audit-mode`.

3. **Engine names** — five (kimi/deepseek/mimo/anthropic/gemini).
   Typos easy.  "kimi-pro" or "deepseek-v4" (which IS the model, not
   the engine).

4. **CLI flag drift** — `harness agent init <target>` vs
   `harness agent init --target <path>`.  AGENT_QUICKSTART.md said
   positional; CLI requires `--target`.  Caught hours after publish.

5. **STATUS.csv ID regex** — `V1.0.0-RC1` broke the validator after I
   assumed dots were OK.  Caught after-the-fact, not before.

6. **Default `max_tokens=2000`** in the audit panel scripts —
   truncated 2/3 engine outputs in the Aquinas review.  Caused real
   information loss.  Closed by W12-B-MAX-TOKENS-DEFAULT-RAISE
   directive.

## Part 3: Mitigations already in place (and they work)

- **`harness advanced list`** hides 13 engineering verbs from `--help`
  (W11-HIDE-ADVANCED-VERBS).  Default `--help` stays operator-grade.
- **Typed stubs** (`src/harness/__init__.pyi`) — IDE catches SDK
  signature errors at edit time.
- **Strict input validation** at SDK boundary — `force_engine` not in
  `SUPPORTED_BACKENDS` returns a clear error, not a hallucinated dispatch.
- **STATUS.csv regex enforcement** — invalid IDs FAIL on load
  (proven 2026-05-25 when V1.0.0-RC1 broke it).
- **`harness preflight`** is the operator's "am I oriented?" gate.
- **`harness today`** is the daily 30-second pulse.

## Part 4: Mitigations MISSING (proposed in the audit)

| Mitigation | Effort | What it prevents |
|---|---|---|
| `harness whoami` — single command listing engines/lens-sets/verbs available NOW | S, 1-2h | Hallucinated engine/lens names |
| Stricter CLI did-you-mean — "Unknown lens 'security-review'. Did you mean 'code-review'?" | S, 2h | Typo'd flag values |
| `FUTURE:` prefix in docs for not-yet-shipped commands | S, 30min | Future-as-present hallucination |
| `harness verbs --recent` — show CLI verbs used in last 7d (after W13-AUDIT-JSONL) | S, 1h | Operator forgets what they actually use |
| STATUS.csv archive when shipped >30d | M, 3-4h | STATUS.csv grows unbounded (currently 358 rows; ~250 shipped) |
| Doc-doc-sync test — CI grep's all `*.md` for `harness <verb>` + fails if verb doesn't exist | S, 1h | Catches future-as-present at PR time |

---

## Part 5: Operator→SDK Shift Map (the second operator question)

Pattern: **anything the operator has to REMEMBER to do can become an
SDK auto-default.**  Operator's job should be policy ("how much to spend
per session"), not procedure ("did I rotate the cache today").

### Tier 1 — Ship tonight (~2-3h total)

| # | Shift | Removes operator burden | Effort | Risk |
|---|---|---|---|---|
| A | Auto-pick `lens-set` from file extension (`.py` → code-review, `.md` → doc-review, `.pdf` → default) | "did I remember the right flag?" | 30min | None — explicit override still works |
| F | Auto-pick `max_tokens` from prompt length (short → 1000, complex → 8000) | "did I cap too low + truncate?" | 1h | None — explicit override still works |
| G | Unify `harness.review()` as SDK function so agent learns ONE API not TWO | "do I use dispatch or review?" | 1-2h | None — additive |

### Tier 2 — This week (~5-7h total)

| # | Shift | Removes operator burden | Effort | Risk |
|---|---|---|---|---|
| B | Auto-snapshot backup before `coord run` or other high-write ops | "did I back up first?" | 1-2h | LOW — fails closed |
| E | SDK auto-retry with fallback engine on transient `success=False` | Agent doesn't write retry logic | 2h | MED — could mask flapping |
| I | Cost-cap pre-check (estimate cost; warn if would exceed budget) | "is this call going to blow budget?" | 1-2h | LOW — purely additive warning |
| J | L5 events inline in `DispatchResult` | Two commands collapse to one read | 1h | LOW — opt-in field |

### Tier 3 — Next week (~2h total)

| # | Shift | Removes operator burden | Effort | Risk |
|---|---|---|---|---|
| L | Default dispatch cache TTL (auto-prune at 7d) | ".harness/dispatched/ growing forever" | 1h | LOW — proven pattern |
| D | Auto-close low-severity observer flags after 7d | "30 stale flags I haven't read" | 1h | MED — could lose signal |

### Anti-recommendations (DO NOT auto)

- **DO NOT** auto-route engines based on task type — strategic decision
  about cost-quality tradeoff should stay visible
- **DO NOT** auto-archive STATUS.csv rows yet — 358 rows is manageable
- **DO NOT** auto-restart the observer — already auto-restarts via
  watchdog; L5 escalation requires operator awareness

### Mandatory mitigations for EVERY auto-default

Without these, auto-defaults become hidden behavior the operator can't
reason about — WORSE than operator burden:

1. **Visible**: log it.  Operator can grep "auto-pruned X dispatches"
   in `harness today`.
2. **Overridable**: explicit flag wins.  `--lens-set default` beats
   auto-pick.  `--max-tokens 500` beats prompt-based heuristic.
3. **Auditable**: write to the W13-AUDIT-JSONL ledger (when it ships).

## Part 6: Open strategic questions

These are the questions the 15-engine panel should weigh in on:

1. **Sequencing**: Wave 13 ops foundation FIRST, or SDK shifts FIRST?
   The runbook + backup are shipped.  Should we add more Wave 13 rows
   (audit JSONL, disk prune, install verify) before doing SDK shifts?
   Or do the shifts BECAUSE they reduce burden + enable Wave 13?

2. **The SDK boundary**: should `harness.dispatch` and `harness.review`
   STAY separate, or merge (Shift G)?  Pros + cons.

3. **Auto-default discipline**: is the "visible + overridable +
   auditable" trio enough?  What's the test that an auto-default is
   safe to ship?

4. **Operator-as-agent**: should we encourage the operator to use
   `import harness; harness.dispatch(...)` from a REPL instead of CLI
   for one-off calls?  Would that reduce CLI bloat?

5. **STATUS.csv at 358 rows**: real problem or non-problem?  Threshold
   for archive?

6. **Hallucination test harness**: should we BUILD a test that fires
   common-misuse patterns (`harness.dispatch(engine='kimi-pro')`,
   `harness review file.md --lens-set security`) + verifies the error
   message is helpful, not confusing?

7. **Documentation rot**: how do we keep the runbook accurate as
   features ship?  CI gate?  Per-commit grep?  Manual quarterly
   review?

8. **Plugin architecture vs internal-tool framing**: Wave 15 plans a
   plugin system for engine adapters.  For an INTERNAL tool, is this
   over-engineering?  Should we just hardcode the 5 engines we use?

9. **The "harness whoami" question**: would a single command answering
   "what can I do right now" actually reduce hallucination, or just
   add another verb to remember?

10. **Backup encryption** (W13-BACKUP-ENCRYPTION row): genuine
    security need or paranoia for an internal tool where .env is
    already on disk in cleartext?

---

## Part 7: What we need from the panel

The panel should produce a **forward plan** — not a list of opinions.
The plan should include:

- A SEQUENCE: which rows to ship in what order, with rationale
- A CUT LIST: rows that should be DROPPED from the plan
- A SHIP LIST: rows that should be ADDED to the plan
- A DECISION TREE: "if X happens, do Y" branches for the 1-2 weeks
  of work ahead
- AN ANTI-PATTERN LIST: things the panel says we should NOT do

The operator needs a plan they can ACT on, not just absorb.
