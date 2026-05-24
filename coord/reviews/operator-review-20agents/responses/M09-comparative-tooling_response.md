### Verdict

`NEEDS-WORK`

### Confidence

0.68

---

### Comparative Analysis

**What xaxiu-harness does that Claude Code CLI, Cursor, and Aider cannot:**

| Capability | xaxiu-harness | Claude Code CLI | Cursor | Aider |
|---|---|---|---|---|
| Multi-engine orchestration (Kimi/DeepSeek/MiMo fallback chains, circuit breaker, proxy) | ✅ | ❌ (Anthropic-only) | ❌ | Partial (multi-model, no orchestration) |
| Spec→Plan→Worker→Integrate autonomous pipeline | ✅ | ❌ | ❌ | ❌ |
| Python SDK for programmatic agent dispatch (`harness.dispatch()`) | ✅ | ❌ (it IS the agent) | ❌ | ❌ |
| L5 escalation watchdog + self-recovery | ✅ | ❌ | ❌ | ❌ |
| Preflight readiness gate before autonomous mode | ✅ | ❌ | ❌ | ❌ |
| Per-engine cost ledger + offload-ratio telemetry | ✅ | Basic | Basic | Basic |
| Dispatch content caching (same packet → cached result) | ✅ | ❌ | ❌ | ❌ |
| Mutation testing canary on live modules | ✅ | ❌ | ❌ | ❌ |
| Context-frugal returns (~36 tokens/dispatch vs ~1500) | ✅ | ❌ | ❌ | ❌ |
| Cross-platform observer (cron + Task Scheduler) | ✅ | ❌ | ❌ | ❌ |
| 20-agent audit panel per commit | ✅ | ❌ | ❌ | ❌ |
| Worktree-isolated parallel workers with dep-branching | ✅ | ❌ | ❌ | ❌ |

**What Claude Code CLI, Cursor, and Aider do better:**

| Capability | Competitors | xaxiu-harness |
|---|---|---|
| CLI encoding reliability | Zero known UnicodeEncodeError crashes | 4 distinct crash paths on Windows cp1252 (evidence 04, 06, 15; Unicode arrows ✓ α → crash) |
| Dashboard as primary surface | Cursor: polished real-time editor integration | Dashboard 3 days stale, missing cost/preflight-latency/L5 widgets (evidence 00, 12, 13, 14 → all 404) |
| Real-time editor integration | Cursor: inline diffs, multi-file edits in-editor | Harness dispatches text; no IDE integration |
| Onboarding friction | Aider: `pip install aider-install && aider` (2 commands) | Harness: 7-file scaffold + DPAPI/.env + Python 3.13+ + engine-specific API keys |
| Interactive editing feedback loop | Claude Code CLI: instant edit→see→iterate | Harness: spec→plan→dispatch→worktree→merge (minutes per cycle) |
| Search/retrieval (RAG) | Cursor: codebase-aware embeddings | Harness: no codebase search; agents must provide context manually |
| Session continuity | Claude Code CLI: conversation memory, auto-compact | Harness: stateless dispatch; agent must manage its own context |
| Multi-file refactoring | Aider: whole-repo awareness in single session | Harness: per-packet scoping; cross-file refactors need multi-worker orchestration |

---

### Top-3 Concrete Recommendations

**1. Fix Windows cp1252 encoding crashes — this is the single highest-severity competitive gap**

One-sentence: Four CLI verbs (`preflight`, `--help`, `agent init --dry-run`, remediation cards) crash with `UnicodeEncodeError` on Windows cp1252 because Click's `echo()` writes Unicode glyphs (→ ✓ α) without `errors='replace'` or forced UTF-8 — the harness's own primary platform.

Evidence: File 04 lines 28-35 (`preflight` crash on `\u2192`), File 06 lines 28-35 (`--help` crash on `\u03b1`), File 15 lines 28-35 (`agent init` crash on `\u2713`). All three are identical `cp1252.py` charmap_encode failures.

Effort: **S** (1-2 hours). Solution: either `set PYTHONIOENCODING=utf-8` in the CLI bootstrap, wrap Click's `echo()` with a UTF-8-forcing wrapper, or replace Unicode glyphs with ASCII equivalents (`->`, `[ok]`, `a`).

Why this matters competitively: