# Wave 2B Batch 2 Security Audit
**Auditor:** general-purpose agent
**Date:** 2026-05-17
**Files audited:** `src/harness/engines/dispatcher.py` (598 LOC), `src/harness/engines/guards.py` (299 LOC)
**Limitations doc consulted:** `spec/ACCEPTED_LIMITATIONS.md` (ACCEPT-1, ACCEPT-2, ACCEPT-3)

## Summary
- HIGH severity findings: 0
- MED severity findings: 3
- LOW severity findings: 4
- Verdict: **safe-to-proceed-to-v0.3.0-commit** (MED items are follow-ups, not commit blockers)

## Per-file findings

### dispatcher.py

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 1 | Validates `project` against `PROJECT_NAME_REGEX` (returns error rather than raises, per "never raises" rule) | PASS | L292-301: `if not re.fullmatch(PROJECT_NAME_REGEX, project): return DispatchResult(..., error="invalid_project_name")` |
| 2 | Loads adapter via `adapters.loader.load_project_adapter(project)` | PASS | L27, L316: `adapter = load_project_adapter(project)` wrapped in try/except for `ValueError, FileNotFoundError` |
| 3 | Reads packet file UTF-8, max 10 MB | PASS | L39, L75-83: `MAX_PACKET_BYTES = 10 * 1024 * 1024`; `_read_packet` enforces `size > MAX_PACKET_BYTES` and uses `p.read_text(encoding="utf-8")` |
| 4 | Picks initial engine via force_engine OR LOCK > BURST > rule > priority | PASS | L164-227: `_pick_initial_engine` enforces hierarchy in exact order — force_engine (L175) → LOCK (L179) → BURST (L185) → rules (L191) → default priority (L223) |
| 5 | LOCK > BURST > per-project rules > global priority (exact ordering) | PASS | Same as #4. Inside the rule branch, `burst` action also consults BURST (L198-202) which is consistent with the hierarchy |
| 6 | `insert_dispatch(...)` returns `dispatch_id` | PASS | L372-377 |
| 7 | Appends to `active_dispatches.json` | PASS | L388-404 via `state_files.append_active_dispatch` |
| 8 | Per engine attempt: calls `engine.dispatch`, times it | PARTIAL/FAIL | L422-426 calls dispatch but does NOT time it locally — it relies on `EngineResponse.latency_ms` set inside concrete.py. Acceptable in practice (concrete sets it). Latency on the wrapped engine-init exception path is hardcoded to `0` (L431) which makes that case unattributable. See finding M-2 below. |
| 9 | On success: update history, remove from active, write jsonl outcome="success", return `DispatchResult(success=True)` | PASS | L436-466. Best-effort error swallowing on the DB/state side is appropriate (operator memory `feedback_status_csv_canonical.md` discipline). |
| 10 | On failure: `insert_fallback`, write jsonl outcome="fallback", switch engine (NEVER same), update engine_health to "degraded" | PASS | L470-487 (health update — transition-only, smart), L573 (`insert_fallback`), L583-593 (jsonl `outcome="fallback"`); L532 `remaining = [n for n in SUPPORTED_BACKENDS if n not in tried]` guarantees never-same. |
| 11 | All eligible engines exhausted: `outcome="all_fallbacks_exhausted"`, `DispatchResult(success=False)` | PASS | L533-565. Properly emits the `"all_fallbacks_exhausted"` outcome (which jsonl_log allows — see jsonl_log.py L25-34). |
| 12 | Caches engine instances per dispatch (no recreate on retry) | PASS | L407 `engine_cache: dict[str, Any] = {}`, L411-414 `_cached_engine` checks cache. |
| 13 | Calls `insert_routing_change(source="cli", ...)` when LOCK/BURST/priority consulted (MED-9 audit trail) | PARTIAL | LOCK at L181, BURST at L187, AVOID-jump at L212. **HOWEVER**, the BURST branch inside a routing-rule match (L199-202) and the default-priority branch (L222-225) do NOT emit a routing_change. See finding M-1 below. |
| 14 | NEVER raises (all errors → `DispatchResult(success=False, error=...)`) | PASS | Every try/except returns instead of re-raising. `_pick_initial_engine` is wrapped in try/except at L354-366. Engine `dispatch()` call is wrapped at L420-433. State-file writes use best-effort swallowing (L401-404, L237-242, L246-264). |
| 15 | Max 1 attempt per engine; tried-engines tracked | PASS | L408 `tried: list[str] = []`, L417 `tried.append(current_engine)`, L532 filters by `not in tried`. |

#### CRITICAL crosschecks (dispatcher.py)

| Crosscheck | Verdict | Evidence |
|---|---|---|
| NEVER logs packet content; only `packet_path` goes to history/jsonl | PASS | grep for `packet_content` in dispatcher: only one occurrence (L329) where it's bound and then ONLY passed to `engine.dispatch(packet_content, ...)` (L423). Never passed to `state_db.*`, `state_files.*`, or `jsonl_log.*`. |
| NEVER includes API keys/response bodies/request headers in `fallback.reason` | PASS | L571 `reason = response.error or "unknown"` — only the `EngineResponse.error` string is used. Concrete engines emit short labels like `"timeout"`, `"network"`, `"HTTP 401"`, `"internal"` (concrete.py L120-145, L213-238, L303-328) — none of which echo the response body or `Authorization` header. |
| All state-file writes atomic per state.files contract | PASS | Dispatcher delegates to `state_files.write_active_dispatches` / `append_active_dispatch`, which call `_atomic_write_json` (files.py L127-145 — tempfile + fsync + os.replace + chmod). |
| Calls `guards.classify_response` on every engine response | **FAIL** | grep `classify_response\|guards` in dispatcher returns **no matches**. The auto-fallback orchestrator dispatches and reads `response.success`/`response.error` raw — it never invokes `guards.classify_response`. **See finding M-3 (MED per ACCEPT-3 protocol).** |

#### dispatcher.py findings

**M-1 (MED): Missing routing_changes audit for two priority-consulting branches**
- L199-202 (burst engine selected from inside a `then.backend == "burst"` rule) does NOT call `_audit_routing_change`. The hierarchy is consulted, but no audit row is written.
- L222-225 (default priority sort when no rule matched) does NOT call `_audit_routing_change`. The "global priority" branch of the v1 §9 hierarchy is therefore silent in the audit log.
- MED-9 amendment text (v1.2-security-amendments.md L26, L395-415) says: "Burst, lock, priority WebSocket mutations have no audit log entry specified" — the amendment focuses on WS mutations but the spirit "audit who/when changed a priority" extends to priority-consulted decisions. Strictly, MED-9 says "WS mutations"; CLI-driven priority defaults aren't mandatory. **Reclassify as LOW if operator considers CLI-priority-consult non-auditable.**
- Severity: **MED** (defensible as LOW).
- Remediation: add `_audit_routing_change("priority_change", chosen_engine, ...)` at L202 (burst-via-rule) and L225 (global-priority default).

**M-2 (MED, per ACCEPT-3): Engine-init failure latency hardcoded to 0**
- L427-433: `except Exception as exc: response = EngineResponse(success=False, text="", latency_ms=0, error=f"engine_init_failed: {exc}")`.
- ACCEPT-3 explicitly notes that the broad `except Exception` in concrete.py buries forensic signal, and that guards.py IS the recovery layer. The dispatcher's own broad-except mirrors that pattern but adds NO label-enrichment (no `_classify_exception(exc)` mapping).
- The `engine_init_failed: <repr>` label LEAKS the raw exception text into the `error` field, which then flows into `state_db.insert_fallback(reason=...)` (L577). If `get_engine` raises `RuntimeError(f"No API key for {name}.")` (concrete.py L383-386), the message itself is fine — but any future engine factory that puts a path or env-var-value into the exception will silently leak into `fallbacks.reason`.
- Severity: **MED per ACCEPT-3** → treat as **LOW** for commit-blocking per the protocol.
- Remediation (Wave 2C): map common exception classes to short labels (`"factory_no_key"`, `"factory_unsupported"`, `"factory_other"`) instead of `f"engine_init_failed: {exc}"`.

**M-3 (MED, per ACCEPT-3): Dispatcher does NOT call `guards.classify_response` on engine responses**
- The packet spec body says: *"Calls guards.classify_response on every engine response? (optional — packet didn't require but it's strongly indicated by ACCEPT-3 — if missing, flag as MED for follow-up)."*
- ACCEPT-3 resolution path explicitly says: *"Wave 2B.4 engine guards will wrap dispatch() and inspect the response shape before it reaches the broad handler."*
- guards.py L113-177 implements `classify_response` exactly to re-label DeepSeek packet-trap / Kimi empty-XML / Anthropic refusal — but **the orchestrator built in dispatcher.py never invokes it**. Consequence: a successful HTTP 200 carrying a DeepSeek v4-flash packet-trap payload will be treated as `response.success=True` (because the concrete returned success on raise-for-status, L104-113 in concrete.py), the dispatcher returns `DispatchResult(success=True, text="<packet-trap JSON>")`, the dispatch never falls back, and the operator gets the trap output.
- Severity: **MED per ACCEPT-3** → treat as **LOW** for commit-blocking per the protocol, but **STRONGLY** flagged as the highest-priority Wave 2B.4 follow-up since this is the entire reason guards.py exists.
- Remediation: in dispatcher.py L436, **before** the `if response.success:` check, insert:
  ```python
  response = guards.classify_response(
      backend=current_engine,
      model=model,
      packet_content=packet_content,
      response=response,
  )
  ```
  Then the existing fallback path (L470+) will fire on `success=False, error="packet_trap"`.

---

### guards.py

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 1 | DeepSeek v4-flash packet-trap: backend=="deepseek" AND model.endswith("-flash") AND text starts with "{" AND contains `"name":` AND contains `"arguments":` → error="packet_trap" | PASS | L137-151. Implements all 5 conditions and returns `EngineResponse(success=False, ..., error="packet_trap")`. |
| 2 | Kimi empty/XML detection: backend=="kimi" AND (text strip empty OR text matches `^\s*<\?xml`) → error="kimi_empty_or_xml" | PASS | L153-162, regex compiled at L53 `_RE_KIMI_XML = re.compile(r"^\s*<\?xml")`. **Minor:** preserves `response.success` rather than forcing False — see L-1 below. |
| 3 | Anthropic refusal: backend=="anthropic" AND first 500 chars match `(?i)i (cannot\|can't\|won't\|am unable)` → error="anthropic_refusal" | PASS | L165-174, regex compiled at L54. Slice `response.text[:500]` (L167) — correctly bounded. **Minor:** preserves `response.success` — see L-1 below. |
| 4 | Otherwise: return response unchanged | PASS | L176-177 |
| 5 | Pure function: no IO, no global state, no logging | PASS | grep for `eval|exec|subprocess|socket|requests|urllib|httpx|open(|os.|print(|sys.` in guards.py → no matches. Only module-level state is compiled regex constants + smart-quote translation table (frozen via `str.maketrans`). |
| 6 | `should_split_kimi_bundle(packet_content)`: True if ≥2 distinct `## ` headers AND total >8KB | PASS | L180-194. Set comprehension on headings (L187-191) handles "distinct" requirement correctly (duplicates collapse to one entry). Size check `len(packet_content.encode("utf-8")) > 8192` (L194). |
| 7 | `split_multi_domain_packet`: returns list of full sub-packet strings, each with the doc preamble | PASS | L197-241. Preamble extracted at L224 (`"".join(lines[:first_heading_idx])`), prepended to each section at L239. Handles edge case of no headings (L220-222 returns whole document). Uses `keepends=True` (L213) so line breaks are preserved across the split. |
| 8 | `anchor_fuzzy_check`: byte-exact / fuzzy / missing classification, returns AnchorReport with LOW/MED/HIGH risk | PASS | L244-299. LOW (all byte-exact), MED (≥1 fuzzy, 0 missing), HIGH (≥1 missing) ordering at L286-291 matches spec. Normalisation applies smart-quote substitution + whitespace collapse (L75-85). |
| 9 | Both anchor and response normalised before fuzzy comparison | PASS | L268 normalises response once; L279 normalises each anchor inline. Correct (asymmetric only — but matching is symmetric because `_normalize_text` is idempotent). |
| 10 | `AnchorReport` is `@dataclass(frozen=True)` | PASS | L88-106. `total/byte_exact/fuzzy_match/missing/risk` all immutable; `risk` typed with `Literal["LOW","MED","HIGH"]`. |

#### CRITICAL crosschecks (guards.py)

| Crosscheck | Verdict | Evidence |
|---|---|---|
| NEVER logs response.text, packet_content, or anchors | PASS | No `print`, no `logging`, no file IO anywhere in the module. |
| All regex patterns module-level compiled | PASS | L53-55 (3 compiled patterns). No inline `re.compile` or `re.match`/`re.search` with string literals inside hot path. |
| No eval/exec/subprocess/network | PASS | Grep confirmed: no matches for any of these. |
| AnchorReport is frozen dataclass | PASS | L88. |

#### guards.py findings

**L-1 (LOW): Rules 2 and 3 preserve `response.success` instead of forcing False**
- L158 `success=response.success` (Kimi empty/XML), L170 `success=response.success` (Anthropic refusal).
- The packet spec (Rule 1) sets `success=False` explicitly (L147 — correct for DeepSeek packet-trap because the HTTP call succeeded but the content is garbage).
- For Rule 2 / Rule 3, the original `response.success` will almost always be True (the engine returned an HTTP 200 with content; it's the *content* that's bad). Preserving `success=True` while setting `error="kimi_empty_or_xml"` is an internally inconsistent EngineResponse (success implies error=None per typical convention) and — combined with the dispatcher's check `if response.success: return DispatchResult(success=True, ...)` — would **suppress fallback** for Kimi empty bodies and Anthropic refusals if integrated.
- Severity: **LOW** (because dispatcher does not currently call classify_response — see M-3 — but once M-3 is fixed this becomes the next bug).
- Remediation: change L158, L170 to `success=False`.

**L-2 (LOW): packet_content parameter is unused but kept in the signature**
- L117 takes `packet_content: str` but the function body never references it (L137-177).
- Docstring at L130-131 acknowledges this: *"unused by the current rule set, but part of the stable API contract"*. Documented, intentional, future-proofs for content-aware classifiers (e.g. "if packet asked for a patch and response contains no FIND/REPLACE blocks → label `"no_patch_block"`"). Not a security issue, but worth noting because callers may not realise they can pass `""`.
- Severity: **LOW (informational)**.

**L-3 (LOW): Anthropic refusal regex is broad**
- `(?i)i (cannot|can't|won't|am unable)` (L54) will fire on legitimate text that happens to contain "I cannot recommend X" or "I can't tell from the diff alone, but…" in the first 500 chars. False positives push to fallback, costing money. Not a security risk; correctness/cost concern only.
- Severity: **LOW**.
- Remediation: tighten to a sentence-start anchor like `(?i)^\s*(i (cannot|can't|won't|am unable)|sorry, i)`.

**L-4 (LOW, per ACCEPT-1): No file mode chmod issues — guards.py touches no files**
- N/A — guards.py is pure. ACCEPT-1 doesn't apply here, but noting the absence for completeness.

---

## Cross-file findings (integration)

**Does dispatcher call guards.classify_response?**
**NO.** dispatcher.py has no `import guards` and no `classify_response` call. See finding M-3. This is the most consequential gap in the batch — without it, the entire detection layer in guards.py is dead code from the orchestrator's perspective. The packet description acknowledged this was optional but "strongly indicated by ACCEPT-3" — and ACCEPT-3's resolution path literally specifies it.

**Is the LOCK/BURST/priority hierarchy correctly ordered?**
**YES.** `_pick_initial_engine` (L164-227) walks force_engine → LOCK → BURST → routing rules → default priority → first-supported fallback. Inside a routing rule that selects backend `"burst"`, the BURST resolver is re-consulted (L198-202) — consistent with the hierarchy. AVOID-priority engines are bumped to the next eligible during rule resolution (L207-218). Correct.

**Does fallback chain correctly use guards-enriched error labels for the next-engine selection?**
**N/A** because dispatcher does not call guards. Currently the fallback chain uses raw `EngineResponse.error` strings (`"HTTP 401"`, `"timeout"`, `"network"`, `"internal"`) from concrete.py. The label-driven engine-selection (`feedback_engine_anchor_accuracy.md`) is NOT in the orchestrator — the dispatcher just picks the next-highest-priority not-yet-tried engine (L567 `_eligible_engines(health, exclude=set(tried))`). This is acceptable as a v0.x default but means guards.py's enriched labels would only be useful for forensics/jsonl, not for routing decisions. Worth a Wave 2C task.

**Both files import from `harness._constants` for shared identifiers (not redefining)?**
**MOSTLY YES.**
- dispatcher.py L26: `from harness._constants import PROJECT_NAME_REGEX, SUPPORTED_BACKENDS` ✓.
- guards.py: imports `EngineResponse` from `harness.engines.base` ✓; does NOT need _constants (no backend list or regex re-defined).
- **Minor inconsistency:** `harness.engines.base` redefines `SUPPORTED_BACKENDS = ["deepseek", "kimi", "anthropic"]` at L19 (base.py) — this duplicates `_constants.SUPPORTED_BACKENDS`. dispatcher.py imports from `_constants` (good), but the duplicate in base.py is a latent drift risk noted as **L-5 (LOW)**. Not introduced by this batch.

**No `eval`/`exec`/`subprocess` in either file?**
**CONFIRMED CLEAN.** Grep across `src/harness/engines/` returns no matches for `eval(|exec(|subprocess|shell=True`.

**All file IO uses explicit `encoding="utf-8"`?**
**YES (dispatcher).** Only one IO point in dispatcher: L83 `p.read_text(encoding="utf-8")`. Explicit and correct. guards.py performs no IO.

**No hardcoded credentials, debug endpoints, or backdoors?**
**CONFIRMED CLEAN.** Grep for `sk-|api_key|password|secret|Bearer` in both files: no matches in dispatcher.py or guards.py.

**dispatcher tracks routing_changes for LOCK/BURST/priority decisions?**
**PARTIAL.** LOCK (L181), BURST-direct (L187), and AVOID-skip (L212-217) write audit rows. The BURST-via-rule branch (L199-202) and default-priority branch (L222-225) do NOT. See finding M-1.

---

## Verdict

**safe-to-proceed-to-v0.3.0-commit**

Rationale:
- Zero HIGH findings.
- M-1, M-2, M-3 are MED but all three are **non-blocking**: M-1 is a defensible-as-LOW audit-coverage gap; M-2 is ACCEPT-3-covered (Wave 2C label-mapping); M-3 is the most important follow-up but is explicitly framed in the packet as "optional, MED for follow-up" and ACCEPT-3 protocol degrades it to LOW for blocking purposes.
- All security guarantees in the dispatcher.py module docstring (L7-15) are upheld: never raises ✓, never logs packet content ✓, fallback reasons use audited `EngineResponse.error` strings ✓, audit-trail invocation present at three of five priority-consult sites.
- guards.py meets every per-packet requirement; the four LOW findings are correctness-polish, not security gaps.

**Strongly recommended pre-tag follow-ups (Wave 2B.5 or Wave 2C, in priority order):**
1. **Wire `classify_response` into dispatcher** at L436 (resolves M-3, the highest-value item).
2. Fix L158 / L170 in guards.py to force `success=False` for Rules 2 & 3 (resolves L-1).
3. Add `_audit_routing_change` calls in dispatcher.py at L202 and L225 (resolves M-1).
4. Replace `engine_init_failed: {exc}` with a label-map (resolves M-2).
5. De-duplicate `SUPPORTED_BACKENDS` in `engines/base.py` (resolves L-5; not introduced by this batch but uncovered during audit).

---

### Counts
- HIGH: 0
- MED: 3 (M-1, M-2, M-3 — M-2 and M-3 downgraded to LOW for blocking per ACCEPT-3)
- LOW: 4 (L-1, L-2, L-3, L-5; L-4 N/A)
- **Verdict: safe-to-proceed-to-v0.3.0-commit**
