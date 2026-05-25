# Horizon C — Internal Tool Variant

**Reframing**: 2026-05-25 operator directive: *"let's try to reach
horizon C, but treat this as an internal tool."*

**Original Horizon C** (commercial/public-product framing) targeted:
plugin architecture + hosted offering + marketplace listings +
multi-user + business-model decision.  Estimated 600-1000h.

**Internal-tool Horizon C** targets: a tool the operator + their
collaborators can DEPEND ON for 1-3 years of real work.  Different
success criteria, different sequencing, ~200-400h total.

---

## What changes vs the original Horizon C

### DROP (was Horizon B/C distribution work)
- PyPI publish + public package
- VSCode Marketplace + JetBrains Marketplace listings
- Landing page + demo videos + blog post + HN submission
- Discord / public discussion forum
- Comparative content vs Aider/Cursor/Claude Code
- Hosted SaaS offering + billing infrastructure
- Open-source-vs-commercial business decision
- Outside-contributor onboarding / governance

### KEEP (still load-bearing for an internal tool)
- Plugin architecture for engine adapters (so adding a new engine
  is hours, not days)
- Multi-user features rescoped: shared cost ledger + per-user budget
  caps for the operator's team, NOT for strangers
- Reliability work: more uptime, better error messages, graceful
  degradation
- Maintenance discipline: locked deps, regression CI, migration path

### ADD (new for internal-tool focus)
- **Backup + restore** for dispatch cache, observer state, budget
  ledger — protects against laptop death or disk failure
- **Disaster recovery runbook** — what to do when the laptop dies,
  the API key rotates, an engine goes down
- **More engine adapters** for resilience: Gemini fully wired, local
  llama.cpp as last-resort fallback, Mistral as another paid option
- **Operator runbook** — written knowledge that survives the
  next-Claude-session's context window
- **Internal deployment automation** — make the VPS install / update
  / rollback path single-command, not manual
- **Secrets rotation procedure** — what to do when an API key leaks
  or expires
- **Disk space management** — caches grow forever right now; need
  size-aware pruning beyond just preflight-latency's 7-day TTL

---

## Workstream sequencing (internal-tool Horizon C)

### Wave 13 — Operations Foundation (~30-40h)

**Goal**: the harness survives the operator going on vacation for a
month and coming back to a working laptop, expired API keys, and
half the engines down.

| Row | Scope | Effort |
|---|---|---|
| W13-OPERATOR-RUNBOOK | docs/INTERNAL_OPERATOR_RUNBOOK.md with "laptop died / key rotated / engine down / restore-from-backup" sections | S, 3h |
| W13-BACKUP-RESTORE | `harness backup` (daily snapshot of .harness/ + coord/observer/ + dispatch ledger) + `harness restore <archive>` + test that round-trips clean | M, 4-5h |
| W13-SECRETS-ROTATION | `harness secrets rotate kimi` walks the operator through key rotation; updates .env + DPAPI + tests connectivity | S, 2-3h |
| W13-DISK-PRUNE | size-aware cache pruning across .harness/dispatched/ (currently grows forever) | S, 2h |
| W13-AUDIT-JSONL | every `harness.dispatch` call appends to `~/.harness/audit.jsonl` for forensic review (DeepSeek panel finding) | S, 2h |
| W13-CI-DRIFT-GATE | weekly CI step that fires a real call per engine + fails if any engine has broken its API shape | S, 2h |
| W13-LOCK-DEPS | lock requirements.txt to exact versions + add `harness self-check` to detect dep drift | S, 2h |
| W13-INSTALL-VERIFY | E2E test that `git clone + pip install -e . + harness review <doc>` works on a clean Windows shell | M, 3-4h |

**Why this wave first**: every row protects against existential risk
(data loss, key rotation, engine drift, dep rot).  Once Wave 13 lands,
the operator can leave the harness alone for a month and come back
to it.

### Wave 14 — Engine Pool Expansion (~25-35h)

**Goal**: reduce single-engine dependency.  Today: Kimi + DeepSeek +
MiMo + Anthropic + Gemini (last two not in active rotation).  Target:
6+ engines including a $0/offline fallback.

| Row | Scope | Effort |
|---|---|---|
| W14-GEMINI-WIRE | fully wire Gemini as a production fallback target (currently stub) | M, 4-5h |
| W14-MISTRAL-ADAPTER | new engine: Mistral La Plateforme API (paid, different vendor) | M, 5-6h |
| W14-LOCAL-LLAMA-FALLBACK | last-resort fallback to local llama.cpp / Ollama for offline operation | L, 8-10h |
| W14-BEST-OF-N | for critical work, dispatch to N engines + pick best response (currently first-wins only) | M, 4-5h |
| W14-ENGINE-HEALTH-FORECAST | predict engine failure from latency trends + cooldown history before it actually fails | M, 4-5h |

### Wave 15 — Plugin Architecture (~40-60h)

**Goal**: adding a new engine takes < 2 hours instead of the current
~1 day.  Same for adding a new lens-set, a new review template, a
new audit lens.

| Row | Scope | Effort |
|---|---|---|
| W15-ENGINE-ABI | define + freeze the engine adapter ABI; refactor existing 5 engines into the new pattern (no behavior change) | L, 12-15h |
| W15-LENS-PLUGIN | lens-sets become plug-in: drop a Python file in plugins/lenses/ and `harness review --lens-set <name>` finds it | M, 5-6h |
| W15-REVIEW-TEMPLATE-PLUGIN | review templates (the synthesis Markdown shape) become customizable per use-case | M, 5-6h |
| W15-PLUGIN-DOCS | docs/PLUGIN_GUIDE.md walks a future-agent through adding a new engine | S, 3h |
| W15-CONTRIB-TESTS | test pattern + fixture helpers for plugin authors | M, 4-5h |

### Wave 16 — Multi-User / Team (~30-40h) — ONLY if operator has a team

**Goal**: 2-5 internal users sharing the same harness deployment with
per-user audit + per-user budget + shared cost-ledger visibility.

| Row | Scope | Effort |
|---|---|---|
| W16-USER-CREATE | `harness user create <name>` issues a user_id + per-user .env directory | S, 3h |
| W16-PER-USER-LEDGER | dispatch ledger gains user_id field; cost-today shows per-user breakdown | M, 4-5h |
| W16-PER-USER-CAP | per-user budget cap (in addition to session cap); auto-escalate when user-cap reached | M, 4-5h |
| W16-SHARED-AUDIT | shared audit trail with user attribution; observer flags any user pattern that looks off | M, 5-6h |
| W16-TEAM-DASHBOARD | dashboard view that shows who's dispatching what (with optional masking) | M, 5-6h |

**Skip this wave entirely if the operator works solo on the harness.**

### Wave 17 — Internal Deployment Hardening (~25-35h)

**Goal**: the VPS install / update / rollback path is a single command
the operator runs without thinking.  No more "spaghetti MySQL update
function" energy.

| Row | Scope | Effort |
|---|---|---|
| W17-DEPLOY-SCRIPT | `bin/deploy-harness.sh <vps>` does: rsync src/ + restart service + run smoke + report verdict | M, 4-5h |
| W17-ROLLBACK | `bin/rollback-harness.sh <vps>` reverts to previous deployed commit + restarts | S, 2-3h |
| W17-VPS-OBSERVER | observer on the VPS that pings the operator's laptop if the VPS-side harness wedges | M, 4-5h |
| W17-CONFIG-AS-CODE | VPS config (cron entries, env vars, port bindings) checked into the repo, not configured manually | M, 4-5h |
| W17-VPS-SECRET-MGMT | secrets on the VPS via systemd-creds or similar; NEVER live in shell history or plain .env | M, 5-6h |
| W17-VPS-BACKUP | the W13-BACKUP-RESTORE work extended to also back up the VPS state on a daily timer | M, 4-5h |

---

## Recommended sequence

For an internal tool, **operations dominate distribution**.  The
sequence I'd ship in:

1. **Wave 13** (operations foundation) — protects everything else
2. **Wave 14** (engine pool expansion) — reduces single-source risk
3. **Wave 15** (plugin architecture) — makes future engines + lenses cheap
4. **Wave 17** (VPS hardening) — only if operator actually uses the VPS path
5. **Wave 16** (multi-user) — only if operator has a team

**Total estimated effort**: 200-400h depending on which waves apply.
~12-25 weeks of part-time work, or ~6-10 weeks if pushed.

---

## What I'd start with TONIGHT

Within the current session, the highest-leverage move is:

**W13-OPERATOR-RUNBOOK** + **W13-BACKUP-RESTORE** in the same commit.

Why this pair:
- The runbook captures the knowledge from this entire session arc
  (12 commits, panel-driven fixes, real-client-task workflow, the
  v1.0 RC tag) BEFORE the next-Claude-session loses context.
- Backup closes the existential data-loss risk: if the laptop dies
  tonight, the harness's dispatch cache + observer state + budget
  ledger are recoverable.
- Both are bounded (~3h + ~5h) and demonstrably ship.
- Both make the harness MORE of an internal tool, not less.

After that:
- W13-AUDIT-JSONL (small, foundational, DeepSeek-flagged in the planning panel)
- W13-DISK-PRUNE (small, future-proofing)
- W13-INSTALL-VERIFY (closes the biggest unverified risk from the master audit)

---

## Risks that change under the internal-tool framing

| Original Horizon C risk | Internal-tool re-rating |
|---|---|
| Nobody wants this | **MUCH LOWER** — the operator is the validated user |
| Anthropic / OpenAI launches similar | **MUCH LOWER** — internal tools aren't competing for users |
| Discord moderation overhead | **GONE** — no public users |
| Open-source vs commercial decision | **GONE** — neither, it's internal |
| Marketplace approval gates | **GONE** |
| Outside contributor governance | **GONE** |
| Documentation for strangers | **REDUCED** — only the operator + collaborators need docs |
| **Operator burnout** | **HIGHER** — the operator is the sole maintainer; sustainability of the harness = sustainability of the operator's attention |
| **Key-person dependency** | **NEW HIGH RISK** — if the operator stops working on it, there's no community to keep it alive. Mitigations: the runbook + locked deps + audit JSONL all reduce the "must-be-the-original-author-to-touch-it" surface |
| **Engine API drift** | **HIGHER stakes** — the operator depends on this in real work; a broken engine breaks the operator's day |

---

## What success looks like in 6 months

The operator can:
- Run `harness review <any-document>` on real client work, get a useful
  3-engine cross-check in 3-5 minutes, $0 cost
- Lose their laptop on Monday, restore the harness from backup on
  Tuesday, lose < 1 day of dispatch history
- Rotate the Kimi API key in 5 minutes via `harness secrets rotate kimi`
- Add a sixth engine (say, Mistral) in 2 hours instead of a day
- Have a collaborator (student, junior reviewer) use the harness with
  their own budget cap + audit trail
- Trust the dispatch ledger as the source of truth for "what work was
  done this month + what did it cost"
- Wake up to a morning email that summarizes overnight observer flags

The non-goals (vs the public Horizon C):
- No PyPI listing
- No VSCode extension
- No marketing site
- No outside users

---

## One-sentence target

> Build an internal tool that the operator can DEPEND ON for 1-3 years
> of real client work, with a backup-and-restore story that survives
> hardware failure, an engine pool that survives any single vendor
> failure, and a runbook that survives the next-Claude-session's
> context limits.

That's the Horizon C internal-tool target.  Achievable in 200-400h
across 4 waves.  Tonight: start with the runbook + backup.
