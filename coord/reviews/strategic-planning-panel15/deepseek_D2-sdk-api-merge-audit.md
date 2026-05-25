## D2-sdk-api-merge-audit (deepseek) – Strategic Forward Plan

### 1. Lens-specific findings

**Core question**: Should `harness.dispatch()` and `harness.review()` merge into a single SDK function, or stay separate? I examine both sides, then rule.

#### Side A: Merge (Shift G from the bloat‑audit)

- **Pro**: “Unify harness.review() as SDK function so agent learns ONE API not TWO” (bloat‑audit, Part 5, Tier 1 Shift G). Fewer functions = simpler mental model for the agent.
- **Pro**: Review *is* dispatch + synthesis. The bloat‑audit states: “Review is already dispatch + synthesis” (implied by the shift description). Under the hood, `harness.review` in `src/harness/review.py` calls `harness.dispatch` three times. The synthesis step is just a post‑processing pipeline. A merged function could take a `mode` parameter (`single`, `review`, `compare`).
- **Pro**: Future extensions (audit, compare) are just variants of the same pattern: dispatch to N engines, synthesize results. “Do they extend dispatch or review?” (bloat‑audit, Part 6, question 2). They extend the *review* pattern, so having a single extensible function is cleaner than two parallel ones.
- **Pro**: Reduces CLI bloat risk. The master audit notes that “30+ CLI verbs” already strain the operator’s cognitive load (Bloat Risk: MEDIUM and growing). Merging SDK functions would mirror a CLI merge, reducing the surface.

#### Side B: Keep separate (add `harness.review()` as a new SDK function instead)

- **Pro**: Dispatch is a low‑level primitive (prompt → one response). Review is a high‑level composite (multi‑engine, lens‑driven, synthesis). The agent’s mental model is clear: “When I want a single answer, I dispatch; when I want a multi‑perspective analysis, I review.” Merging them would conflate two distinct intents.
- **Pro**: Return types differ. `DispatchResult` has `.summary`, `.text`, `.full()`. A review produces a `ReviewResult` with per‑engine artifacts, a synthesis Markdown, and output directory. Merging would require a union return type or a complex polymorphic result — type stubs become messy and IDE autocomplete degrades. The current SDK is already “context‑frugal” (~36 tokens per dispatch per AGENT_QUICKSTART); review returns many more tokens.
- **Pro**: Breaking change risk. The bloat‑audit says “None — additive” for Shift G, but that’s only if we *add* `harness.review` to the SDK without changing `dispatch`. Merging would require a deprecation path, new signature, and migration for all existing `harness.dispatch` callers — there are “81 .text‑callers across worker/integrator/coord/tests” (STATUS.csv W11‑CONTEXT‑FRUGAL‑RETURN‑LAZY). That’s a real migration cost for an internal tool with tight operator time.
- **Pro**: Future extensions (audit, compare) are naturally methods on a `ReviewManager` or separate functions, not variants of dispatch. The bloat‑audit’s own plan adds `harness.review()` as a separate verb (W12‑B‑INSTANT‑REVIEW). Extending review is simpler if it remains independent.

#### Rule: **Keep separate, but add `harness.review()` as a new SDK function**

The arguments for staying separate are stronger for an internal tool with a single operator who needs clarity, not ceremony. The agent’s mental model is better served by two clear primitives than one overloaded one. The concrete evidence:

- “The SDK surface is **3 public functions** (dispatch, retrieve, budget_status)” (master audit, 1. Where we are right now). Adding a 4th function `review` is a small, backward‑compatible addition — no deprecation, no migration.
- “Review is a multi‑engine dispatch + synthesis” is exactly why it deserves its own identity. A merged function with a `mode` parameter would bury the synthesis logic inside the dispatch code path, violating single‑responsibility.
- The bloat‑audit itself fell into a contradiction: it recommends merging as Tier 1 Shift G (“low effort, additive”) but later lists `harness review` as a shipped CLI verb (W12‑B‑INSTANT‑REVIEW). The CLI already treats them separately; the SDK should follow that pattern.

So the ruling: **Do not merge. Ship `harness.review()` as a new standalone SDK function in Wave 13, keeping `harness.dispatch()` unchanged.** Below is the concrete API design, migration path, and deprecation timeline (which is zero for dispatch — no deprecation needed).

#### Concrete API design

```python
# Add to src/harness/__init__.py (re-export)
def review(
    content: str | Path,
    *,
    lens_set: str | None = None,       # default: auto‑pick from file extension
    engines: list[str] | None = None,  # default: [kimi, deepseek, mimo]
    max_tokens: int | None = None,     # default 6000 (per W12‑B directive)
    out_dir: str | None = None,        # default coord/reviews/review-<basename>/
    return_synthesis_only: bool = True # if True, return SynthesisResult (lightweight);
                                       # if False, return ReviewResult (with per‑engine artifacts)
) -> SynthesisResult | ReviewResult
```

`SynthesisResult`:
- `.synthesis` (str) — the cross‑engine synthesis Markdown
- `.summary` (str) — 300‑char head+tail
- `.engines_used: list[str]`
- `.cost_usd: float`
- `.duration_sec: float`
- `.__repr__` returns summary only (context‑frugal by default)

`ReviewResult`:
- Contains `.synthesis` + `.per_engine_results: dict[str, DispatchResult]` + `.artifacts_dir: Path`
- `.__repr__` returns synthesis, full text lazy via `.full()` on each engine result

#### Migration path for existing callers

- **CLI users**: `harness review` already works (shipped in W12‑B). No change.
- **SDK callers who currently invoke `harness.review()` via CLI subprocess**: No such callers exist — review was CLI‑only. Adding `harness.review()` is purely additive.
- **Any future SDK caller**: Use either `harness.dispatch()` for single queries or `harness.review()` for multi‑engine analysis. Both coexist.

#### Deprecation timeline

No deprecation is needed. `harness.dispatch` remains unchanged. `harness.review` is added in v1.0.0‑rc.2 / v1.0.0 final. After 12 months, if the split proves wasteful, we can consider a unified `harness.process(mode=...)` but that is deferred to Horizon C.

---

### 2. Recommended SHIP list (my top 3‑5 rows to do FIRST, given the merge ruling)

**1. W13‑AUDIT‑JSONL** (bloat‑audit Part 4, STATUS.csv W13‑AUDIT‑JSONL)  
*Why*: Every `harness.dispatch()` and `harness.review()` call should write to an audit trail. This supports the merged‑API decision by giving us telemetry to decide 12 months from now whether dispatch and review calls follow distinct patterns. Also a DeepSeek panel finding.

**2. W13‑INSTALL‑VERIFY** (master audit §5)  
*Why*: “The single hardest unknown: whether `pip install -e .` actually works end‑to‑end on a clean machine.” If the install path is broken, the AGENT_QUICKSTART promise is broken, and any new SDK function (including `harness.review()`) will fail on first contact. Fix this before adding more API surface.

**3. W12‑B‑MAX‑TOKENS‑DEFAULT‑RAISE** (STATUS.csv)  
*Why*: Already to‑do, and directly affects `harness.review()` quality. The default 6000 tokens must be baked into the new SDK `review()` function. Ship this first so the review function’s defaults are correct.

**4. New row: `harness.review()` SDK function** (see ADD list below)  
*Why*: This is the direct output of my ruling. Within 1‑2 hours, we can add the Python function that wraps the existing `review_document` logic and re‑export it from `harness.__init__.py`. Add 5 new tests. No changes to existing code.

**5. W13‑DISK‑PRUNE** (bloat‑audit Part 4)  
*Why*: Review artifacts (per‑engine JSON and synthesis Markdown) accumulate indefinitely. We need size‑aware pruning before `harness.review()` becomes a daily tool. Low effort, high future value.

---

### 3. Recommended DROP list (my top 2‑4 rows to NOT do)

**1. W13‑BACKUP‑ENCRYPTION**  
*Why*: For an internal tool where `.env` is already in cleartext on disk, encrypting the backup adds complexity with minimal security gain. DeepSeek flagged it (STATUS.csv “cross‑engine review of horizon‑c plan”), but the threat model doesn’t warrant the 3‑4h investment. **Drop** until the operator stores secrets outside the repo.

**2. W13‑PLUGIN‑SANDBOX‑PLAN**  
*Why*: The plugin architecture (Wave 15) is 6‑12 months out. Planning sandboxing now is premature. The source pack says “internal tool = trusted authors”. The code‑injection risk is real but accepting it is fine for the intended use. **Drop** from the immediate plan; revisit when plugins exist.

**3. W16‑MULTI‑USER features** (if operator works solo)  
*Why*: The master audit directly says “Skip this wave entirely if the operator works solo on the harness.” With no evidence of a team, these rows (W16‑USER‑CREATE, etc.) waste effort. **Drop** unless the operator explicitly requests them.

**4. W13‑VPS‑OBSERVER‑NAT‑PLAN**  
*Why*: This is a decision row for Wave 17, which is also far out. The operator doesn’t have a VPS deployment yet (no user‑facing hosted version). **Drop** to free time for higher‑impact items.

---

### 4. Recommended ADD list (my top 1‑3 NEW rows worth adding)

**1. W13‑SDK‑REVIEW‑FUNCTION** (the concrete add)  
*Pitch*: Add `harness.review(content, lens_set=None, engines=None, max_tokens=6000, out_dir=None)` as a new public SDK function, wrapping the existing review engine and returning `SynthesisResult`. This implements the ruling immediately.  
*Effort*: S (1‑2h, 5 tests)

**2. W13‑REVIEW‑CACHE‑SMART‑OUTPUT**  
*Pitch*: For `harness.review()`, cache per‑engine responses so re‑reviewing the same file (after small edits) reuses cached results if the content hash matches. Reduces cost and latency for iterative review.  
*Effort*: M (4‑5h, reuse dispatch_cache)

**3. W13‑REVIEW‑DEFAULT‑LENS‑FROM‑EXTENSION** (Tier 1 Shift A)  
*Pitch*: Auto‑select the lens set based on file extension (`.py` → code‑review, `.md` → doc‑review, `.pdf` → default). Already identified in the bloat‑audit as 30min work. Lowers operator’s cognitive load when using `harness.review()`.  
*Effort*: S (0.5‑1h)

---

### 5. Single most important recommendation

> **Implement `harness.review()` as a separate SDK function this evening, keep `harness.dispatch()` unchanged, and fix the `pip install -e .` path before you ship v1.0.0 final — that pair of actions validates the two‑primitive API design and unblocks the tool for real daily use.**