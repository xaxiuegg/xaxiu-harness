### 1. Lens-specific findings

**Finding 1: The AGENT_QUICKSTART install promise is unverified — I will discover this the hard way on first contact.**  
Verbatim: *"every command we ran used `PYTHONPATH=src python -m harness`. The AGENT_QUICKSTART claims `pip install -e .` works. We never verified."* (master audit, §3). As an agent, my first action is `git clone && pip install -e .`. If this breaks, I burn my entire context window debugging setuptools before I ever dispatch a prompt.

**Finding 2: Future-as-present doc rot creates guaranteed failure loops.**  
Verbatim: *"runbook describes `harness secrets rotate kimi` (doesn't exist). DeepSeek's cross-engine review... flagged this exact issue. Future-Claude would try it + fail + waste a cycle."* (bloat audit, §2). I consume docs to plan my actions. Every fictional command in the runbook is a hallucination landmine planted by the authors, not by me.

**Finding 3: Silent output truncation already destroyed real client work.**  
Verbatim: *"Default `max_tokens=2000` in the audit panel scripts — truncated 2/3 engine outputs in the Aquinas review. Caused real information loss."* (bloat audit, §2). I rely on `summary` and `full()` to be complete. If defaults silently truncate, I will ship incomplete analysis to a client without knowing it.

**Finding 4: The 24h autonomous survival claim — the one that matters for unattended operation — is unresolved.**  
Verbatim: *"The 24h autonomous test is the load-bearing claim that hasn't resolved yet... resolves only when tomorrow's `v1-rc1-24h-report.sh` produces a clean output."* (master audit, §6). I need to know the harness won't die overnight and leave my scheduled work orphaned.

**Finding 5: No SDK-side ground truth exists to prevent me from hallucinating engine or lens names.**  
Verbatim: *"`harness whoami` — single command listing engines/lens-sets/verbs available NOW"* is listed under *"Mitigations MISSING"* (bloat audit, §4). Without this, I have to guess whether `deepseek-v4` is an engine name or a model name, or whether `security-review` is a valid lens.

---

### 2. Recommended SHIP list (your top 3-5 rows to do FIRST)

1. **W13-INSTALL-VERIFY** — *"E2E test that `git clone + pip install -e . + harness review <doc>` works on a clean Windows shell"* (horizon-c plan). If the AGENT_QUICKSTART onboarding is false, no other feature matters; I will abort on first use.

2. **Tier 1 Shift G** — *"Unify `harness.review()` as SDK function so agent learns ONE API not TWO"* (bloat audit, Part 5). Every additional top-level function I must remember increases my chance of inventing non-existent flags; collapsing review into the SDK reduces my cognitive surface.

3. **Missing mitigation: `harness whoami`** — *"single command listing engines/lens-sets/verbs available NOW"* (bloat audit, §4). I need to query ground truth programmatically instead of trusting docs that describe not-yet-shipped commands.

4. **Tier 1 Shift F** — *"Auto-pick `max_tokens` from prompt length (short → 1000, complex → 8000)"* (bloat audit, Part 5). Prevents another *"real information loss"* event like the Aquinas truncation.

5. **W13-AUDIT-JSONL** — *"every `harness.dispatch` call appends to `~/.harness/audit.jsonl`"* (horizon-c plan). When I resume in a future session, this ledger lets me reconstruct what the previous agent did without relying on operator memory.

---

### 3. Recommended DROP list (your top 2-4 rows to NOT do)

1. **W13-BACKUP-ENCRYPTION** — The horizon-c plan notes *.env is already on disk in cleartext*; encrypting backups while secrets sit exposed is security theatre that delays the operational fixes I actually need. Defer until after install-verify and engine health.

2. **W15-PLUGIN-ARCHITECTURE** — The internal plan itself asks: *"For an INTERNAL tool, is this over-engineering? Should we just hardcode the 5 engines we use?"* (bloat audit, §8). I don't need an ABI refactor; I need the existing 5 engines to be rock-solid. Plugin systems introduce instability I can't afford in client work.

3. **W16 Multi-User / Team** — *"Skip this wave entirely if the operator works solo"* (horizon-c plan). The operator has 1-3h evenings + 5h weekends; there is no team. Building per-user RBAC and team dashboards is pure opportunity cost.

4. **W13-PLUGIN-SANDBOX-PLAN** — The internal-tool framing means all authors are trusted. Accept the risk, document it, and drop the 2-3h planning row so I can get engine health instead.

---

### 4. Recommended ADD list (your top 1-3 NEW rows worth adding)

1. **SDK `harness.meta()` (or `whoami()`)** — Structured JSON export of valid engines, lens-sets, SDK version, and available CLI verbs, callable from Python. Pitch: gives agents ground truth to eliminate hallucination of engine names and lens sets. Effort: **S, 1-2h**.

2. **CI doc-doc-sync gate** — *"CI grep's all `*.md` for `harness <verb>` + fails if verb doesn't exist"* (bloat audit, §4). Pitch: prevents future-as-present doc rot from ever entering the repo again, so my training on the docs doesn't include fictional commands. Effort: **S, 1h**.

3. **Agent-mode preflight** — `harness preflight --json --agent` returning structured readiness (keys loaded, cache dir writable, engine ping results) as machine-parseable JSON, not human prose. Pitch: lets me verify my environment programmatically without parsing ASCII tables meant for an operator. Effort: **M, 3h**.

---

### 5. Single most important recommendation

**Verify `pip install -e .` end-to-end on a clean machine and ship `harness whoami` so the SDK's onboarding promise is provably true and agents can query ground truth instead of hallucinating against stale docs.**