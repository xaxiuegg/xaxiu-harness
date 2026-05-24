<!-- persona=R6-user-research-proxy status=OK (38186ms) -->

# R6-user-research-proxy

**1. Headline verdict**
YES-IF — but only if the next 1-2 waves flip the product inside-out from infrastructure-first to interaction-first; as currently oriented, 0 of the 5 personas ever reach their first answer.

**2. Wave-count estimate**
5 waves p50 (W11-W15), 3-8 p90. The lower bound assumes W11 ships a working "ask" verb + standalone installer and W12-W15 polish trust, hiding, and cost visibility. The upper bound assumes continued infrastructure-first prioritization that keeps leaking UX debt forward.

**3. The 3 most load-bearing W11 decisions**

| # | Decision | Why it's load-bearing |
|---|----------|----------------------|
| 1 | **Ship `harness ask "<question>"` as the primary verb.** One command. Auto-selects healthy engine. Returns the answer in terminal. Zero config, zero preflight gate. This is the missing faucet — right now the harness is all plumbing, no spout. Every persona below bounces because there's nothing to *do* after install. | Without this, the product has no user-facing purpose for a chat-tier user. Full stop. |
| 2 | **Eliminate the git_clean preflight blocker via a first-run path that never triggers it.** Either `harness start wizard` creates a clean working tree silently, or preflight downgrades git_clean from FAIL to WARN on a fresh clone with no user commits. The W10 panel's 8/10 "WITH GUARDRAILS" and 2/10 "NO" both cite this as the single concrete failure point. | Every persona hits this wall on day one. It's the front door with a deadbolt. |
| 3 | **Ship a one-file installer (`.bat` or embedded Python zip) that replaces `git clone && pip install`.** Doesn't need to be .msi yet — even a `harness-setup.bat` that downloads, extracts, and runs `pip install -e .` silently is enough. | The parent, teacher, and small-business owner never reach preflight because they're already gone at the install step. |

**4. The one thing to CUT or HIDE**
**Coord V2 multi-agent worktree pipeline** — bury every coord subcommand behind `harness --advanced` or a `harness advanced` namespace. The 13 coord verbs, worktree isolation, heartbeat streams, and Planner→Worker→Coordinator→Integrator concepts are invisible complexity to all five personas. Even the hobbyist coder won't use them until they're deep into the tool. Showing them in default `--help` actively signals "this tool is not for you."

**5. The one risk most likely to derail the trajectory**
**The team continues to iterate on infrastructure (observer recovery, mutation pattern expansion, async flips, cost widgets) while the interaction surface remains absent.** Every wave in the snapshot is dispatch-layer, detection-layer, or coordination-layer work. There is zero user-facing interaction model — no "ask," no "chat," no "do this task." If W11 ships observer self-recovery and L5 escalation contracts instead of the "ask" verb and installer, the trajectory doesn't stall — it actively diverges from the chat-tier user, who will never know the harness exists.

**6. Single-sentence recommendation**
Pivot W11 hard: build the faucet (`harness ask`), fix the front door (first-run / installer), and hide the plumbing — because today a chat-tier user downloads the repo, fails preflight, and uninstalls before they ever type a question.

---

**Persona journey annex** (condensed):

| Persona | Drop-off point | Closest to fit? |
|---------|---------------|-----------------|
| Parent trying Kimi | Never passes `git clone` | No |
| High-school teacher | Fails preflight, doesn't know what "engine" means | No |
| Small-business owner | Sees YAML config, closes terminal | No |
| Journalist | Wants "paste article → summary"; no such path exists | No |
| Hobbyist coder | Might survive install + preflight; asks "now what?" and finds only infra verbs | **Closest, but still a 3/10** — they'll use it if `harness ask` exists and the CLI feels like a smart API wrapper, not a DevOps toolkit |

The hobbyist coder is the natural beachhead. But even they need a reason to stay past minute five, and that reason is currently missing.
