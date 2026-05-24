# AQUINAS Student Project Brief — Mentor Review Synthesis

**Date**: 2026-05-24
**Reviewed by**: 3 LLM engines via xaxiu-harness multi-engine dispatch
- Kimi (subscription, integrity audit lens, 157s, $0)
- DeepSeek (paid, technical + security audit lens, 16s, $0)
- MiMo (subscription, purpose + realism lens, 32s, $0)

Total cost: **~$0**. Total wall-clock: **2m 37s** (parallel).

---

## Bottom-line for the mentor

The brief should **not** be accepted at face value. All three engines
independently converged on the same core finding: **the system is hand-tuned
rule-based scoring being presented as machine learning**, with significant
technical and security gaps and substantial copy-paste artifacts.

This is a perfectly respectable undergraduate scope IF presented honestly
as "weighted rule-based classification" — but it is presented as
econometrics + scikit-learn + ML loop, which it demonstrably is not.

---

## Convergent findings (flagged by 2+ engines independently)

### 1. The "ML loop" is fundamentally mis-described

**Kimi #7**: *"Theta is defined as the scalar difference between model
output and a human label (a prediction residual), yet it is
simultaneously asserted to be the coefficient adjustment magnitude — two
distinct mathematical objects that are not interchangeable."*

**DeepSeek Technical #1 (HIGH)**: *"This is not gradient descent — it
is an ad-hoc error-driven adjustment that cannot converge reliably or
generalize."*

**MiMo Finding 2**: *"The 'loop until Theta approaches 0' description
lacks a convergence threshold, a learning rate, a loss function, or any
indication of what library runs it."*

**What this means for the meeting**: ask the student to *show you the
code* that performs the update step. If they cannot point to a learning
rate, an optimizer, or a loss function, this is not ML.

---

### 2. The coefficient table reveals hand-tuning, not learning

**Kimi #3**: *"No training data, holdout set, loss function, or scikit
estimator is described, and the coefficient table is populated with
hand-set integers, so the 'ML' label is unsubstantiated."*

**DeepSeek Technical #4 (HIGH)**: *"The coefficient table contains
fixed integers and a `hard_rule` flag. No evidence of automated
learning; the loop appears to be manual coefficient tweaking."*

**MiMo Finding 1**: *"Betas are clean integers (35, 15, −100, −90,
−80) with no decimal precision, no training procedure, no loss curve,
no validation split. The −100 and −90 values... are labeled
`hard_rule: TRUE`, which means they are effectively binary
kill-switches, not learned parameters."*

**What this means**: ask to see the actual `LogisticRegression().fit()`
call or equivalent. If the integer betas in the spec match what's in
the code, no training happened — this is a weighted-sum classifier
with hand-picked weights.

---

### 3. The `D_bundle36250.63666` debug-leak artifact

**Kimi #1**: *"A raw numeric literal is embedded in the dummy-variable
name, which is characteristic of copying a cell reference or debug
output without cleaning or understanding its role in the model."*

**MiMo Finding 2**: *"A data value that has leaked into a variable
name, almost certainly a copy-paste artifact from a spreadsheet into
the document."*

**What this means**: the brief was not carefully reviewed by someone
who understood it. A single piece of weak evidence by itself, but
combined with the rest, it points to AI-assisted drafting without
operational understanding.

---

### 4. Scikit-learn is claimed but not demonstrated

**Kimi #3**: claims of "Scikit Learning" with no evidence.

**DeepSeek Technical #6 (MEDIUM)**: *"The brief provides no code or
description of using `sklearn` to train a model... no evidence of
calling `LogisticRegression().fit()` or similar. The sklearn
integration is claimed but not demonstrated."*

**MiMo Finding 2**: *"UPDATE vaguely references 'the addition of
Scikit Learning' but provides zero sklearn artifacts: no model class,
no `.fit()`, no hyperparameters, no cross-validation."*

**Note**: the brief includes the scikit-learn algorithm cheat-sheet
image on page 5 — which is a publicly-circulated sklearn marketing
infographic, not original work. Its inclusion without commentary
suggests it was pasted to *look* like ML proof.

---

### 5. Domain incoherence: flooring → welding without explanation

**Kimi #4**: *"The coefficient table contains verbatim flooring-product
factors such as `flooring_text`, `m2_conversion_success`, and
`pieces_per_box_found`, but the brief abruptly pivots to `Welding
material taxonomy (HS codes)` and a `Specific welding equation` for
HS code 7229. There is no explanation for how a flooring dataset
morphs into a welding-classification model, suggesting sections were
copied from unrelated sources."*

**MiMo Finding 3**: Aquinas Discovery (the keyword news scraper)
is a third unrelated project. *"'Connected through API for security
reasons' is a non-sequitur — API connectivity does not establish that
two systems belong in the same project brief."*

**What this means**: the brief is **three projects** stitched together:
flooring classifier (real), welding classifier (claimed, possibly
sketched), and economic news keyword scraper (separate prototype).
Ask the student to demo each independently.

---

### 6. Self-assessed accuracy with zero evidence

**Kimi #6**: *"The brief itself asserts: '4411 analysis is very
detailed and pretty accurate' and 'The accuracy is getting better and
better through more and more trials.' No precision/recall figures,
confusion matrix, or holdout evaluation is provided."*

The student's own taxonomy includes `DANGEROUS_OVERCLAIM: "Any output
pretending correlation proves causation"` — Kimi notes the brief
itself qualifies under its own label.

**What this means**: ask for: (a) the confusion matrix on a holdout
set, (b) the false-positive / false-negative breakdown by category,
(c) inter-annotator agreement if there's a manual ground-truth.

---

## Unique findings (flagged by only one engine, still worth raising)

### Technical (DeepSeek-only)

- **DeepSeek Technical #2 (MED)**: *"Hard-coding the sign (±) of
  logistic coefficients assumes the direction of influence is known
  in advance, contradicting the purpose of estimation."* The
  `Score_7229` equation has `+beta1*D_wire` but `-beta6*D_nonalloy`.
  In a real fit you let the data decide the sign.
- **DeepSeek Technical #5 (MED)**: The logistic function `Lambda` is
  named but never applied — `Score_7229 = ...` is a linear score, not
  a probability. So the "logistic regression" is actually a linear
  discriminant.

### Security (DeepSeek-only, was being expanded when output cap hit)

- **CRITICAL — Unauthenticated FastAPI endpoints**: *"There is zero
  mention of authentication, API keys, or OAuth. Any attacker can
  call `/analyse` and `/analyse-json` to inject data or extract
  predictions."*
- (Cut off but extrapolating from the verbatim spec): the
  `processor lock returning 409` is a concurrency primitive, not a
  security primitive. Uploads directory + Excel report generation =
  classic file-upload-driven attack surface (path traversal, XLSX
  formula injection). No mention of input validation, rate limiting,
  TLS, or secret storage. **VPS deploy without auth = open to the
  internet**.

### Realism (MiMo-only)

- **MiMo Finding 4**: Three structural variants coexist (Architect 1
  monolithic Qt/QML, Aquinas_VPS, legacy/) with comments like
  *"leftover from old combined package"*. This reflects rewrite
  history, not deliberate architecture. Whichever variant runs is
  the "real" one — ask which one the student actually uses, and why
  the others are still in the tree.

### Drafting quality (Kimi-only)

- *"The MySQL updating function is still to spaghetti and needed to
  be refined"* — the student's own EBI flags a known problem they
  haven't fixed.
- *"user interference and experience"* — interference vs interface.
- *"weather a product is classied in what catogorized has nwo been
  fully quantified"* — three errors in one sentence in the UPDATE
  block claiming the system is "now fully quantified".

---

## Specific questions to ask the student

1. **Show me the optimizer loop.** Where is the gradient computed?
   What is the learning rate? Where does the loss function live? If
   the answer is "the coefficients are in a CSV I edit by hand",
   that's not ML — that's expert-system scoring.

2. **Run `git log` on the coefficient table.** If the integer betas
   have been edited by the student rather than written by a training
   script, the "Aquinas_Learning" loop is not happening.

3. **Show me precision/recall on a holdout.** Without an evaluation
   number, "very detailed and pretty accurate" is sentiment, not data.

4. **Demo `/analyse` from the public internet.** If you (the mentor)
   can `curl` the endpoint without an API key from your home
   network, the VPS deployment is unauthenticated and that's a
   blocking security problem.

5. **Explain `D_bundle36250.63666`.** This is the most concrete
   integrity test in the brief. A student who wrote this themselves
   can immediately explain what happened. A student who copy-pasted
   will guess or deflect.

6. **Which architecture is live?** Architect 1, Aquinas_VPS, or both?
   If both, why? If just one, why is the dead one still in the tree?

7. **Show me Aquinas Discovery scoring an actual news article.** The
   keyword JSON is just a JSON file — it doesn't score anything
   without a runner. Where is the runner?

---

## Mentor verdict

The undergraduate is doing real work on a *plausible* core (data
parsing + rule-based scoring + a Qt/QML GUI + VPS deploy is a fine
scope). But the brief overclaims by labeling rule-based scoring as
econometrics + ML + sklearn, and the security posture for the VPS
endpoint is genuinely concerning.

**Recommendation**: don't reject the project — request a revised brief
that (a) accurately describes the system as weighted rule-based
classification, (b) provides concrete evaluation numbers, (c) adds
auth to the FastAPI before the VPS goes anywhere near production,
and (d) either ships sklearn for real or removes the ML language.

---

## Process notes (for the harness operator)

- 3 engines, 3 distinct lenses, run in parallel via `harness.dispatch`
- Total cost: **$0** (all 3 were subscription engines for this query)
- Total wall time: **2m 37s**
- All 3 engines independently converged on the load-bearing findings
  (#1-#6 above) — strong cross-engine signal
- DeepSeek + MiMo hit the `max_tokens=2000` output cap mid-section.
  For deeper audits, raise that to 4000.
- Artifacts at `coord/reviews/aquinas-student-review/`
