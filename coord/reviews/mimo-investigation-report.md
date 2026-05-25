# MiMo Investigation Report — for peer review

**Author**: Claude (in-session)
**Date**: 2026-05-25
**Status**: hypothesis + evidence — operator requested peer verification
before acting on conclusions.
**Reviewers needed**: cross-engine peer review (NOT just my own analysis).

---

## 1. Original problem

3 separate dispatches across the session had **all MiMo personas fail**
with the harness error `"internal"`:

| Dispatch | Source pack | max_tokens | MiMo result |
|---|---|---|---|
| 15-engine panel Round 1 | 96 KB | 8000 | 0/5 MiMo succeeded |
| MiMo retry with smaller pack | 21 KB | 6000 | 1/5 (only M3) |
| 3-engine final-verdict Round 2 | 34 KB | 8000 | 0/1 |

This led me to conclude (in earlier syntheses) that MiMo had a
**content-filter trigger on strategic/risk language**.

The operator's directive: *"Investigate mimo before we proceed. I want
its perspective."*

---

## 2. Investigation methodology

### 2a. Code-level finding

`src/harness/engines/concrete.py` line 676 contains:

```python
except Exception:
    latency_ms = int((time.monotonic() - start) * 1000)
    return EngineResponse(
        success=False,
        text="",
        latency_ms=latency_ms,
        error="internal",
    )
```

This is a **bare `except Exception`** that swallows the real error and
remaps it to the string `"internal"`. The harness's own
`feedback_no_silent_loops` memory explicitly warns against this pattern.

**Implication**: every "internal" error we observed could have been any
underlying exception — `HTTPStatusError`, `TimeoutException`,
`ConnectError`, or any other. The wrapper hides the cause.

### 2b. Test matrix to isolate the real cause

I wrote `scripts/investigate_mimo_failures.py` to bypass the
`MimoEngine` wrapper with raw `httpx.Client` calls so the real
exception type would be visible. 8 tests:

| # | Variable | Result |
|---|---|---|
| T1 | bare smoke ("reply pong", 10 chars, max_tokens=100) | **OK** in 3.7s |
| T2 | 297-char prompt, no risk vocabulary, max_tokens=2000 | **OK** in 19.8s |
| T3 | 337-char prompt WITH security/risk vocabulary, max_tokens=2000 | **OK** in 53.5s |
| T4 | bloat-audit content (9626 chars / ~2906 tokens) summarize, max_tokens=1500 | **OK** in 14.4s |
| T5 | bare strategic prompt (449 chars, no source), max_tokens=2000 | **OK** in 21.8s |
| T6 | T5 prompt + model=mimo-v2.5 (not -pro) | **OK** in 11.3s |
| T7 | T5 prompt + max_tokens=8000 | **OK** in 23.6s |
| T8 | T5 prompt + max_tokens=500 | **OK** in 14.4s |

**Result**: 8/8 succeeded. Eliminated:
- Content-filter on security/risk vocabulary (T3 worked, 5581 chars output)
- Context-window for medium-size prompts (T4 worked at 9.6KB)
- max_tokens issue alone (T7 worked at 8000)
- Model-specific issue (both mimo-v2.5 and -pro worked)

### 2c. Round 2: test the variables I HADN'T isolated

`scripts/investigate_mimo_failures_round2.py` tested the 2 variables
not covered in Round 1: large prompts + concurrent dispatch.

| # | Variable | Result |
|---|---|---|
| T9 | 97KB panel-size prompt sequential, max_tokens=5000 | **OK** in 50.5s |
| T10 | T9 × 3 concurrent | **All 3 OK** in 45s |
| T11 | T9 with max_tokens=8000 | **FAIL** in 60.8s — `RemoteProtocolError: Server disconnected without sending a response` |
| T12-25KB | 25 KB incremental size, max_tokens=2000 | **OK** in 57s |
| T12-50KB | 50 KB | **FAIL** in 60.8s — `RemoteProtocolError` |
| T12-75KB | 75 KB | **FAIL** in 60.8s — `RemoteProtocolError` |
| T12-100KB | 100 KB | **OK** in 52.2s |

### 2d. One more test (sequential simple-prompt at 4000)

`scripts/mimo_final_verdict_only.py` sent a 36KB structured 5-section
verdict prompt sequentially at max_tokens=4000.

**Result**: FAIL in 61.0s — `RemoteProtocolError: Server disconnected`.

A simpler 3-question (SHIP/DROP/action) prompt at 2500 max_tokens
against the same content is running concurrently with this peer review.

---

## 3. My hypothesis (the claim under peer review)

**Primary hypothesis**: MiMo's upstream API has a **server-side latency
budget around 60s**. When the model's reasoning time exceeds that (due
to structured prompts asking for verdict-style judgment, or due to high
max_tokens producing long generation), the server **disconnects without
sending a response**.

**Secondary hypothesis**: The harness's `MimoEngine.dispatch` wrapper
masks this `RemoteProtocolError` (and possibly other transient errors)
as the opaque string `"internal"`, causing us to misdiagnose the issue.

**Why I think this**:
- T9 (97KB simple "list 3 SHIP + 3 DROP") succeeded in 50.5s — under 60s
- T11 (97KB + max_tokens=8000 = more generation = more time) failed at 60.8s
- T12 sporadic pattern (25→50→75→100) suggests server-side variance, not deterministic content rule
- All failures show `RemoteProtocolError: Server disconnected without sending a response` — TCP-level disconnect, not application-level error
- Failures occur at ~60s — a suspiciously round timeout

**Why I'm hesitant to over-claim**:
- T12 pattern is non-monotonic (100KB succeeded after 75KB failed) — suggests SERVER LOAD VARIANCE, not deterministic ~50KB threshold
- I haven't checked MiMo's official documentation for their stated request timeout
- I haven't tested with `stream=true` (which might bypass the 60s budget)
- I haven't tested with different network conditions
- The wrapper bug (bare `except`) and the API behavior (timeout) are
  TWO findings — both real, but the relative weight is unclear

---

## 4. Conclusions I'm tempted to draw (peer review THESE)

### Claim A: The harness wrapper bug is real and should be fixed

`except Exception: error="internal"` at line 676 hides the actual
error from operators and from future investigations. Fix: catch
explicit exception types and preserve the actual `repr(exc)` in
the error field.

**Confidence in claim A**: HIGH (it's literally in the code).

### Claim B: MiMo isn't blocking strategic content

The content-filter theory is now disproved. T3 (explicit security risk
review request) succeeded. T5 (bare SHIP/DROP question) succeeded.

**Confidence in claim B**: HIGH (8/8 tests in Round 1 succeeded with
strategic content).

### Claim C: MiMo's API has a ~60s server-side timeout

Every failure observed in Round 2 came in at 60.8s with
`RemoteProtocolError`. Same error, same timing. Not a coincidence.

**Confidence in claim C**: MEDIUM-HIGH. Strong correlation but the
60s timeout assumption is mine, not from MiMo's docs.

### Claim D: The trigger is "reasoning time", not "input size"

T9 (97KB input, simple ask) succeeded.
T11 (97KB input, max_tokens=8000) failed.
T12-100KB (100KB input, simple summarize ask) succeeded.
T12-50KB and T12-75KB (smaller input, similar simple ask) failed.

This suggests something more than just input size. But the T12 50/75/100
pattern is hard to explain — possibly server load variance.

**Confidence in claim D**: MEDIUM. The "reasoning time" framing is
plausible but I don't have a way to measure MiMo's internal compute
time.

### Claim E: Sub-5000 max_tokens with non-structured prompts is the safe zone for MiMo

T9 worked. T10 (3× concurrent of T9) worked.

**Confidence in claim E**: MEDIUM. One-shot test of one prompt shape.

---

## 5. What I'm asking peers to evaluate

1. **Methodology critique**: did my 8+7 tests actually test the right
   variables? What did I miss?

2. **Alternative explanations**: is there a hypothesis I'm not
   considering that would also fit the data?

3. **Confidence calibration**: are my HIGH/MEDIUM ratings on claims
   A-E reasonable?

4. **Next-tests suggestion**: if you wanted to verify my hypothesis,
   what's the single best next test?

5. **Wrapper fix design**: should the harness catch each specific
   httpx exception type and preserve the cause, or is the current
   wrapper acceptable?

6. **Operational recommendation**: given the data, what's the right
   MiMo usage policy going forward?

---

## 6. Raw data attached

- `coord/reviews/mimo-investigation-output.txt` — Round 1 test outputs (8 tests)
- `coord/reviews/mimo-investigation-round2.txt` — Round 2 test outputs (7 tests)
- `scripts/investigate_mimo_failures.py` — Round 1 script
- `scripts/investigate_mimo_failures_round2.py` — Round 2 script
- `src/harness/engines/concrete.py` lines 600-683 — the MimoEngine source

---

## 7. What I am NOT going to do without peer verification

- Patch the `MimoEngine` wrapper to surface the real error (waiting for
  peer review to confirm the bare-except is the right fix)
- Update any policy or STATUS row claiming "MiMo unreliable for
  strategic work" (the prior synthesis claim is now suspect — needs
  retraction or amendment)
- Re-fire the strategic panel with corrected MiMo params (waiting for
  peer review to converge on what those params should be)

The operator's epistemic check is correct: a single-investigator report
with self-confidence ratings is not a basis for action.
