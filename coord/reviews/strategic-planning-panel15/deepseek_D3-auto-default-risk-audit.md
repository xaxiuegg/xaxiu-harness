## D3-auto-default-risk-audit (DeepSeek) — Strategic Forward Plan

### 1. Lens-specific findings

**Finding 1: Auto-max_tokens heuristic risks silent truncation (HIGH)**  
The most concrete auto-default failure already observed: in the Aquinas review, `max_tokens=2000` “truncated 2/3 engine outputs … Caused real information loss” ([master-audit](coord/reviews/master-audit-2026-05-25.md), §6). An auto‑pick heuristic based on prompt length would reproduce this silently if it picks too low for a complex document. The operator may not notice for weeks unless `truncated=True` is surfaced aggressively.

- **Worst case**: A critical analysis is cut mid‑sentence, the operator trusts the output, makes a wrong client decision.  
- **Guardrail**: Every `DispatchResult` where `truncated=True` must log the auto‑picked `max_tokens` and include a `⚠ OUTPUT TRUNCATED at N tokens` in the summary line. Also run a post‑dispatch check: if `truncated=True` and the prompt length exceeds the auto‑picked cap by >20%, emit a L3 observer flag.

**Finding 2: Auto-retry fallback can mask permanent API key failure (HIGH)**  
The bloat audit rates auto‑retry risk as MED, but from a silent‑failure lens it’s higher: “could mask flapping” ([bloat-audit](coord/reviews/bloat-audit-2026-05-25.md), Tier 2 row E). The real danger: a key expires, auto‑retry falls back to another engine for every dispatch, and the operator never sees the original engine fail for 14 days. When they need that engine (e.g., for a specific capability), it’s dead with no warning.

- **Worst case**: The primary engine is dead for two weeks; all dispatches silently use a sub‑optimal fallback engine (higher latency, different quality). Operator loses trust in the pool.  
- **Guardrail**: After each auto‑fallback, log the primary failure reason + fallback engine used in `DispatchResult.fallback_chain`. If the same primary engine fails >3 times in 24h, raise a L3 “Primary engine X repeatedly failed — check API key” flag. Surface total fallback count in `harness today`.

**Finding 3: Auto-close low-severity flags removes early warnings (HIGH)**  
The bloat audit says “could lose signal” ([bloat-audit](coord/reviews/bloat-audit-2026-05-25.md), Tier 3 row D). That is an understatement. Low‑severity flags (e.g., “observer tick took 3× longer than usual”) may be the first symptom of a degrading system. Auto‑closing them after 7d removes the operator’s only trace of that precursor. By the time the problem escalates to HIGH, root cause is hidden.

- **Worst case**: A disk‑space warning auto‑closes after 7d; operator never sees it. 10 days later cache fills, `preflight` fails, and the operator has to debug from scratch.  
- **Guardrail**: Do **not** auto‑close low flags without operator acknowledgment. Instead, auto‑escalate flags that persist unreviewed for 7d to L3 and archive them with a link to the original event. Add an `auto_closed` count to `harness today`.

**Finding 4: Auto-snapshot backup without integrity check creates false security (CRITICAL)**  
The bloat audit rates auto‑snapshot risk as LOW (“fails closed”), but silent corruption or partial failure is worse than no backup. The operator believes they have a restore point; they don’t. The `W13-BACKUP-RESTORE` row shipped without encryption or integrity verification — DeepSeek already flagged “No discussion of encryption” ([STATUS.csv W13-BACKUP-ENCRYPTION](coord/STATUS.csv)). That’s encryption; integrity verification is also absent.

- **Worst case**: 2 weeks of dispatch cache, observer state, and budget ledger are lost when the operator tries to restore after a laptop crash, because every auto‑backup silently failed (disk full, permission denied, or wrote 0 bytes).  
- **Guardrail**: Every auto‑backup must compute and log a SHA‑256 checksum. `harness backup list` should show a `verified` column. If backup fails (zero‑size, checksum mismatch, missing files), emit L4 “Backup integrity failure” and do **not** mark the schedule as successful.

**Finding 5: Auto-lens-set from file extension can cause misclassification (MED/HIGH)**  
The bloat audit says risk is “none” because override works. But a silent mis‑pick — e.g., `.md` file gets `doc-review` when it’s actually code documentation that needs `code-review` — will produce an irrelevant review. The operator may not re‑run with the correct lens for weeks, especially if the output looks plausible.

- **Worst case**: A `.md` file containing critical configuration YAML is reviewed as prose, missing a security misconfiguration. Operator ships the configuration without re‑review.  
- **Guardrail**: Log the auto‑picked lens‑set in the review header and in the audit JSONL. Add a brief note in the synthesis: “Auto-selected lens‑set `doc-review` for `.md` file. Override with `--lens-set code-review` if reviewing code.” This makes the automatic choice visible without forcing a menu.

---

### 2. Recommended SHIP list (top 3–5 rows to do FIRST)

| Row | Why |
|-----|-----|
| **W13-AUDIT-JSONL** (Wave 13) | This is the foundational audit trail that all auto-default guardrails depend on. Without it, auto-defaults are invisible. The bloat audit mandates it: “Write to W13-AUDIT-JSONL ledger” for every auto-default. Ship it before any Tier 1 auto-default. |
| **W13-BACKUP-ENCRYPTION** (Wave 13) | Directly addresses the #1 CRITICAL risk: silent backup corruption or access. Adds encryption + integrity verification to the backup/restore path. DeepSeek flagged this specifically. |
| **New: Auto-default truncation warning** | Add `truncated=True` → summary line `"⚠ OUTPUT TRUNCATED at N tokens"` to the SDK `DispatchResult`. Covers the highest severity auto‑default risk (auto‑max_tokens). Small effort (≤1h). |
| **New: Auto-retry fallback logging + flag** | Log primary failure reason in `DispatchResult.fallback_chain` and raise L3 flag if same primary fails 3×/24h. This closes the silent key-death risk. Estimated 2h. |
| **W13-DISK-PRUNE** (Wave 13) | Already in backlog. Needed because auto‑cache TTL (Tier 3 row L) can delete entries the operator still needs. A size‑aware prune is safer than a blind 7‑day TTL. |

---

### 3. Recommended DROP list (top 2–4 rows to NOT do)

| Row | Why |
|-----|-----|
| **Tier 3 D: Auto-close low-severity observer flags** | Risk of losing early warning signals outweighs convenience. The bloat audit’s mitigation “visible + overridable + auditable” is not enough for this one — the very act of auto‑closing destroys the signal. Replace with auto‑escalate after 7d (see ADD list). |
| **Tier 2 B: Auto-snapshot backup before high-write ops** | Ship only after integrity verification and encryption are added. Otherwise, it creates a false sense of security. Currently not in backlog — but if considered, defer until `harness backup create` is proven in the field. |
| **Tier 1 G: Unify harness.review() as SDK function** | This is an API redesign, not an auto‑default. It adds complexity, risks breaking the SDK contract, and does not reduce operator burden. The two functions `dispatch` and `review` serve fundamentally different use cases. Keep them separate. |
| **W14-BEST-OF-N-COST-CAP (decision row)** | The cost multiplier for best‑of‑N is a real concern, but it belongs to engine expansion (Wave 14), not the auto‑default risk layer. Don’t let it distract from the immediate auto‑default guardrails. |

---

### 4. Recommended ADD list (top 1–3 NEW rows worth adding)

| Row | Pitch | Effort |
|-----|-------|--------|
| **AUTO-DEFAULT-GUARDRAIL-FRAMEWORK** | Enforce the “visible + overridable + auditable” trio for every new auto‑default by a CI test. The test greps for new auto‑default code paths and requires a matching log line, override flag, and audit JSONL write. Prevents future silent failures at commit time. | M (4–5h) |
| **AUTO-ESCALATE-UNREVIEWED-FLAGS** | Instead of auto‑close low flags, auto‑escalate to L3 after 7d of no operator view. Add `harness flags --show-archived` for forensic access. Replaces the dropped D row with a safer alternative. | S (2–3h) |
| **AUTO-MAX_TOKENS HEURISTIC DOCUMENTATION** | Document the heuristic algorithm, its safe defaults (minimum 4000 for analysis, 1000 for quick), and the override flag. Includes a test that verifies the heuristic never picks below the safe floor for complex prompts. | S (1–2h) |

---

### 5. Single most important recommendation

**Ship W13-AUDIT-JSONL and implement the truncation‑warning guardrail for auto‑max_tokens before activating any Tier 1 auto‑default — the Aquinas truncation incident proved this is the single highest‑impact silent failure, and the audit JSONL is the cost‑effective infrastructure to detect all others.**