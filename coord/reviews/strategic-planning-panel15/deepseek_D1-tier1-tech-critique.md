# Strategic Planning Panel — D1-tier1-tech-critique (deepseek)

## 1. Lens-specific findings

My lens audits three Tier 1 shifts proposed in the **Bloat Audit (Part 5)** as “Ship tonight”. Below are grounded critiques using verbatim references.

### Finding 1: Auto-pick `lens-set` from file extension has silent failure modes the plan glosses over

The source pack says:

> **Shift A** – Risk: **None — explicit override still works**.

This is false. Consider:

- A `.py` file that is *not* Python source (e.g. a PyYAML config named `conf.py`) → gets `code-review` lens, misdirects the review.
- A `.yaml` file (common for configs) → no mapping → uses `default` lens, but `code-review` might be more appropriate.
- A `.txt` log file → treated as `default`, but the operator intended `doc-review`.

The override mechanism (`--lens-set default`) exists, but **the auto-pick fires before the operator can think**. The operator may not notice the mis-selection until after the review completes. This is a *gotcha*, not a “none” risk.

The **mandatory mitigations** (part 6, visible/overridable/auditable) are listed but not wired into the design. The plan does not specify how the agent or operator sees *which* lens-set was automatically chosen.

### Finding 2: Auto-pick `max_tokens` from prompt length fights the existing directive and heuristic is unsound

The source pack says:

> **Shift F** – Risk: **None — explicit override still works**.

But this directly contradicts the **operator directive captured in STATUS.csv row `W12-B-MAX-TOKENS-DEFAULT-RAISE`**:

> “we are comfortable with high max token output cap – bake this preference into the harness defaults. … add a **--quick CLI/SDK flag that drops to 1000** for cheap one-shots.”

The operator *already* decided on a **default high cap (6000-8000) + opt-down via `--quick`**. Adding a *length-based heuristic* on top creates:

- **Competing autopilots**: the heuristic may set 1000 for a short prompt that expects a long answer (e.g. `“Explain quantum error correction”` is 3 words but requires 2000+ tokens), losing information.
- **Bad failure mode**: truncation is invisible unless the agent checks `result.truncated`. The heuristic could silently under-generate.
- **Override complexity**: `--max-tokens 8000` would override, but the operator now has to reason about *which* auto-pick is active.

The heuristic is unsound: prompt length does **not** correlate with required output length. A short “Why?” can be analyzed for 5000 tokens; a long code snippet needs only “LGTM” as summary.

### Finding 3: Shift G (unify `harness.review()` as SDK function) is well-motivated but needs a signature audit and test surface before shipping

The source pack says:

> **Shift G** – Risk: **None — additive**.

The motivation is solid: the CLI already has `harness review`, and having `harness.review()` as an SDK function reduces the API surface the agent must learn. However:

- **API design**: the existing SDK has `dispatch()` and `retrieve()`. Adding `review()` will tempt agents to use `review()` for *all* multi-engine work, even when they only need a single dispatch. The signature must **not** hide the ability to do single-engine dispatch via the same function.
- **Failure mode**: `review()` currently blocks on 3 engines (parallel). If one engine hangs, the whole call blocks. The SDK function must support `timeout_sec` per engine and a `fallback_on_timeout` behavior.
- **Override mechanism**: the CLI review accepts `--engine`, `--lens-set`, `--max-tokens`, `--out-dir`. The SDK function must expose the same knobs, not a black-box.
- **Backwards-compat**: adding `review` to `harness/__init__.py` is additive; no existing code breaks. But agents using `import harness` and `harness.dispatch` will now also see `harness.review`; no harm.
- **Test surface**: must test that `harness.review(doc, lens_set='code-review')` produces the same output as the CLI with `--lens-set code-review`, across PDF, TXT, MD, Python files. Also test timeout behavior, and that a single-engine call via `harness.dispatch` remains the correct pattern for non-review work.

---

## 2. Recommended SHIP list (top 3–5 rows to do FIRST)

### 1. **Shift G – Unify `harness.review()` as SDK function**

**Why first**: It’s truly additive, low risk, and directly reduces operator burden (“do I use dispatch or review?”). It also *enables* the auto-pick shifts to be tested cleanly (you can call `harness.review(file, lens_set='auto')` in tests). Ship with the exact signature below.

**Proposed signature**:

```python
def review(
    document: str | Path,           # file path or text content
    *,
    engine: str | list[str] = ["kimi", "deepseek", "mimo"],
    lens_set: str = "default",      # "auto" triggers file-extension heuristic
    max_tokens: int = 6000,         # matches current CLI default
    timeout_sec: float = 600.0,     # per-engine timeout
    out_dir: str | Path | None = None,  # None -> auto-named in coord/reviews/
) -> ReviewResult:
    ...
```

**Test plan**:
- 3 fixture documents: `.py`, `.md`, `.pdf`
- Compare output text of `harness.review(f, lens_set="auto")` vs CLI `harness review --lens-set auto` (the CLI calls the same internal function)
- Override: pass explicit lens_set, engine, max_tokens – ensure they are used
- Timeout: inject a slow mock engine -> verify timeout triggers fallback
- Ensure `ReviewResult` has `.text` (full synthesis) and `.per_engine` list

### 2. **Shift A – Auto-pick lens-set from file extension**

**Why second**: With `review()` as SDK function, the auto-pick is easy to implement and test. However we must **add safety rails** before the “none risk” claim.

**Proposed design**:
- Heuristic function `_pick_lens_set(file_path: str) -> str` returns one of `{"code-review", "doc-review", "default"}`.
- Log the choice at INFO level: `"Auto-picked lens-set 'code-review' for foo.py (override with --lens-set)"`.
- Override: explicit `lens_set` argument wins. The value `"auto"` triggers the heuristic; any other string is taken literally.
- If the heuristic fails (e.g. unknown extension like `.rst`) -> fallback to `"default"` + log warning.

**Test plan**:
- .py -> code-review, .md -> doc-review, .pdf -> default, .txt -> default, .yaml -> default (explicit test), .rst -> default (with warning log check)
- Override: `lens_set="doc-review"` on a .py -> must produce doc-review, not heuristic
- Edge: file with no extension -> default
- Edge: file path with directory but no extension -> default

### 3. **W13-AUDIT-JSONL** (from Wave 13)

**Why third**: The bloat audit (part 5, mandatory mitigations) requires auditable auto-defaults. Without audit-JSONL, we cannot verify that auto-picked lens-sets are being used correctly. This is a **prerequisite** for the auto-defaults to meet the “auditable” criterion.

**Proposed signature** (already outlined in source pack, but I specify it here for concreteness):

```python
# In harness/audit.py
def record_audit_event(event: dict, *, ledger_path: str | None = None) -> None:
    """Append a JSON line to ~/.harness/audit.jsonl with timestamp."""
```

**Test plan**: Append events, read them back, verify timestamp and schema. Test corruption handling (append to non-existent dir creates it, append to corrupted file raises).

### 4. **W12-B-MAX-TOKENS-DEFAULT-RAISE** (already in todo)

**Why fourth**: This is already queued (STATUS.csv: todo). It’s the correct solution for the truncation problem – a high default + explicit `--quick` flag. Ship it **before** any auto-pick max_tokens heuristic, to close the door on Shift F.

**Proposed signature** (from existing spec):
- Change default `max_tokens` in `dispatch()` from 2000 to 8000.
- Add `quick: bool = False` parameter to `dispatch()` and `review()` that sets max_tokens to 1000.

**Test plan**: Verify that dispatching without `quick` uses 8000; with `quick=True` uses 1000. Verify that explicit `max_tokens=500` overrides both defaults.

### 5. **`harness whoami`** (from Bloat Audit Part 4)

**Why fifth**: The helm chart says “would a single command answering ‘what can I do right now’ actually reduce hallucination?”. For our lens, this reduces **engine/lens-set hallucination risk** – a key failure mode. Implement as a cheap, no-dispatch command.

**Proposed signature**:

```python
# harness whoami CLI verb (no SDK function needed)
def whoami() -> dict:
    return {
        "engines": SUPPORTED_BACKENDS,   # only those with keys loaded
        "lens_sets": list(LENS_SETS.keys()),
        "cli_verbs": ["dispatch", "retrieve", "review", "today", ...],
        "session_budget_remaining": budget_status().get("remaining_budget_usd", 5.0),
        "default_lens_set": "auto" if WIP else "default",
    }
```

**Test plan**: smoke test that output is valid dict; test on engine-less environment (no keys) still works; test that it doesn’t hit any network.

---

## 3. Recommended DROP list (top 2–4 rows to NOT do)

### 1. **Shift F – Auto-pick max_tokens from prompt length**

**Drop entirely**. Reasons:
- **Conflicting directive** (STATUS.csv `W12-B-MAX-TOKENS-DEFAULT-RAISE`) already has a better solution.
- **Unsound heuristic**: prompt length does not predict output length. The failure mode (silent truncation) is worse than the operator burden of occasionally specifying `--quick` or `--max-tokens 2000`.
- **Risk is not “none”**: the plan claims “None — explicit override still works”, but the *default outcome* is now unpredictable. An agent that trusts the default may get truncation without warning. Shift A’s auto-pick is more benign (wrong lens-set is less damaging than truncated output).
- **Effort**: 1h to implement + more to test all edge cases. Better spent on W12-B-MAX-TOKENS-DEFAULT-RAISE which is already spec’d.

### 2. **W13-BACKUP-ENCRYPTION** (Status: todo, from DeepSeek review)

**Drop from immediate plan**. The existing backup already **excludes .env** (per source pack W13-BACKUP-RESTORE: “NEVER backs up: .env”). API keys are never in the backup archive. The DeepSeek panel flagged this as a risk, but for an *internal tool* where the operator controls the laptop and the backup destination (local disk, not cloud), the threat model is acceptable. Adding AES-256 encryption adds ~3-4h of cryptographically sensitive code that needs security review – not worth it. If the operator later stores backups on cloud storage, revisit. For now: resolve as “accepted risk, document in runbook”.

### 3. **W13-PLUGIN-SANDBOX-PLAN** (Status: todo, from DeepSeek review)

**Drop as a work item**. This is a decision row, not an implementation row. For an internal tool (only trusted authors), we accept the risk of code injection from plugins. Document in `PLUGIN_GUIDE.md`: “Plugins are Python files executed in the harness process. Only load plugins from authors you trust.” No sandbox needed. The effort (~2-3h) should be redirected to the actual plugin ABI implementation (Wave 15).

### 4. **W13-VPS-OBSERVER-NAT-PLAN** (Status: todo)

**Drop or defer to Wave 17**. The VPS observer is in Wave 17, which is far out. The decision about NAT traversal is premature until we actually deploy a VPS. Moreover, the simplest workaround – laptop polls VPS – is already captured in the existing `observer` architecture (the observer on laptop can check in, no need for VPS to ping laptop). The runbook already describes manual checks. Defer until deployment experiments reveal a real problem.

---

## 4. Recommended ADD list (top 1–3 new rows)

### 1. **“Auto-pick lens-set: implement safety rails”** (S, ~1h)

Add to the pending work for Shift A: (a) log the chosen lens-set at INFO level, (b) support a `lens_set="auto"` keyword in both CLI and SDK to *explicitly* invoke the heuristic (default remains `lens_set="default"` so no surprise), (c) emit a warning if the heuristic is used and the file extension is unknown. This changes the risk from “none” to “low and visible”. Must accompany the mandatory mitigations from Bloat Audit Part 6.

### 2. **“Test hallucination harness for common misuse”** (M, ~3-4h)

From Bloat Audit Part 4/6 – **open strategic question #6**: “should we BUILD a test that fires common-misuse patterns + verifies the error message is helpful?” I strongly recommend adding this now because it directly addresses the failure mode of **lens-set/engine hallucination** (a key risk for auto-pick features). It would prevent regressions like the CLI flag drift caught in W11. The test suite would:

```python
def test_hallucinated_lens_set():
    result = subprocess.run(["harness", "review", "foo.py", "--lens-set", "security-review"], capture_output=True, text=True)
    assert "security-review" in result.stderr and "Did you mean" in result.stderr

def test_hallucinated_engine():
    result = harness.dispatch("test", engine="kimi-pro")
    assert "kimi-pro" in result.error_excerpt and "Did you mean 'kimi'?" in result.error_excerpt
```

This reduces the operator’s debugging load and makes the system more forgiving.

### 3. **“`harness.review()` SDK timeout test + timeout signal”** (S, ~1h)

Add a dedicated test that fires `harness.review(doc, timeout_sec=0.1, engine="kimi")` to verify that a single-engine timeout does not hang the whole call. This catches the critical failure mode described in Finding 3. Without this test, G is not safe to ship.

---

## 5. Single most important recommendation

**Ship `harness.review()` as an SDK function (Shift G) this evening with the proposed signature and test plan, but do not wire the auto-pick magic into it until the audit-JSONL log exists and the safety rails are in place – the SDK function is the foundation; the auto-picks are polish that must be auditably logged to avoid hidden failures.**

That single action:
- Removes the `dispatch` vs `review` confusion from the agent’s mind.
- Gives us a stable API to test auto-picks against.
- Delivers immediate value (operator can use `harness.review` in a Python REPL or script).
- Does not break any existing code.
- Builds a clear boundary: the SDK function is the entry point; configuration (including future auto-defaults) is a hidden layer that the operator can introspect via the audit log.