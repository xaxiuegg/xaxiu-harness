"""Multi-engine review of the Aquinas Project Brief.

Operator concerns: integrity, purpose, security, accuracy.
Strategy: dispatch THE SAME source text to 3 engines with 3 distinct
lenses, then synthesize.

Kimi (subscription, $0): integrity audit + claims-vs-evidence
DeepSeek (paid, ~$0.001): technical math + security audit
MiMo (subscription, $0): purpose + realism for academic context

Demonstrates: parallel engine dispatch, context-frugal summaries,
fallback chain not needed (each engine targeted at its strength).
"""
from __future__ import annotations

import concurrent.futures as _cf
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine

OUT_DIR = Path("coord/reviews/aquinas-student-review")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# Source: the operator-supplied PDF, transcribed to text so the 3 engines
# work from the same base.  Verbatim transcription (preserving the
# original misspellings) so the integrity audit can flag them.
SOURCE_TEXT = """\
# Scope of research and development for AQUINAS

## Brief

Phase 1: Come up with an accurate way to filter out the information from a big set of database
- Accurately filter out information from the trade data set through pipelines, validators and parser using Python, SQL, Pandas
- Solidify the architect of the coding -> efficiency, accuracy, stability
- Deploy the project to VPS
- Create GUI for easier user interference and experience
- Fine tuning by hands
- Rules are still set by absolute constant. Through trial and error.

WWW: Absolute coefficients were set. Rules were established. Parser, validators system
proven to work quite well. The accuracy is getting better and better through more and more
trials. VPS version is deployed and the GUI was made and it looks quite stunning. Client and
Server coding work somewhat coherently together. All of the data is automatically saved on.
4411 analysis is very detailed and pretty accurate

EBI: The only struggle that I have encountered throughout this process is 72 files and 8311.
This is due to the fact that these two data sets have a lot of missing factors that lead to the
automation process becoming harder and harder. The solution I had for this is to slowly but
steadily move from Human factor -> Machine Learning concept. The MySQL updating
function is still to spaghetti and needed to be refined.

## Phase 2: Machine Learning

- Utilize all of the processed data from Phase 1, this including hardset constant rules that
  do not change over the course of scripts honings and improving itself trials through trials
- Using the principle of Econometrics, I have successfully made a machine learning script that
  essentially have the ability to review the mistakes that it did through reviewing their own
  mistakes (NULL hypothesis - testing).

Equation: Y = B0 + B1*X1 + B2*X2 + ... + epsilon
(student labels: Y intercept, slope coefficient, error term)

"Beta 0 is the fixed acceptance factor which will be fixed (this could be a binary
variable that would remain constant regardless of any change of coefficient throughout the
process of Machine Learning. Beta(1), Beta(2) -> hence forth, would be a relative coefficient
where it will changes through the process of constant Theta here is the change suggested
change of coefficient within the model Y = B0 ..."

"Essentially means, mathematically we get closer and closer to the concept of being accurate
by minor changes over time."

## Coefficient table

| factor_name           | beta | hard_rule |
|-----------------------|------|-----------|
| flooring_text         |  35  | FALSE     |
| dimension_lw_found    |  15  | FALSE     |
| m2_conversion_success |  25  | FALSE     |
| source_unit_area      |  10  | FALSE     |
| package_area_found    |  18  | FALSE     |
| pieces_per_box_found  |   6  | FALSE     |
| no_flooring_text      | -35  | FALSE     |
| m2_conversion_failed  | -25  | FALSE     |
| sample_display        |-100  | TRUE      |
| packaging_use         | -90  | TRUE      |
| finished_component    | -80  | TRUE      |
| missing_product       |-100  | TRUE      |

Aquinas_Learning ML loop:
  Y(al) = F(X)         (output of Aquinas Learning)
  Y(ac) = accurate output done by me (human label)
  Y(al) - Y(ac) = Theta coefficient need to change
  loop "until Theta approaches 0"

## Econometrics formulation (verbatim)

P(yi=1|Di,Zi) = Lambda(beta0 + sum_j beta_j * D_ji + sum_m gamma_m * Z_mi
                        + sum_{a,b} delta_ab * (D_ai * D_bi))

Where:
  y_i = 1 if item i is flooring; 0 otherwise
  D_ji = dummy variable, either 0 or 1
  Z_mi = continuous variable, such as length/width/thickness/package_area_m2
  Lambda = logistic function

## Welding material taxonomy (HS codes)

8311 = finished welding consumables: coated electrodes, cored wire, coated rods, etc.
7229 = other alloy steel wire
7223 = stainless steel wire
7217 = iron/non-alloy steel wire
7228 = alloy steel bars/rods that can include some welding rod cases

WELDING GROUP { SOLID_WELDING_WIRE, FLUX_CORED_WIRE, STICK_ELECTRODE,
  STAINLESS_WELDING_WIRE, ALLOY_WELDING_WIRE, WELDING_ROD, WELDING_FLUX,
  NOT_WELDING_STEEL, MACHINE_OR_PART, PACKAGING_SAMPLE }

## Architect 1: tables

analysis_runs (run_id, file_name, run_time, processor_version, coefficient_version,
                total_rows, accepted_count, rejected_count, uncertain_count)
row_outputs (run_id, row_number, decision, confidence_score, reasons, product_type,
              coefficients_used, raw_row_snapshot)
correct_truth_sheet (run_id, row_number, correct_decision, correct_category,
                      correction_reason, reviewed_by, reviewed_at)
error_analysis (run_id, false_accept_count, false_reject_count, true_accept_count,
                 true_reject_count, error_reason_group, factor_responsible)
coefficient_versions (coefficient_version, factor_name, product_type, coefficient_value,
                       active_status, created_at, reason_for_change)

Flow:
  Data Input -> Function -> Data Output
  Data Output -> Get checked by Validator -> Error in Judgement
  Error in Judgement -> Saved on MySQL
  Adjustment to Coefficient -> Saved on MySQL
  New run -> Function fetches new adjusted Coefficient on MySQL -> Loop
  Process will essentially be done til Theta approaches 0

## Specific welding equation (verbatim from brief)

Score_7229 =
  beta0
  + beta1 * D_wire
  + beta2 * D_alloy
  + beta3 * D_coil
  + beta4 * D_spool
  + beta5 * D_bundle36250.63666     <-- literal text from PDF
  - beta6 * D_nonalloy
  - beta7 * D_welding
  - beta8 * D_suspected_welding
  - beta9 * D_rod
  - beta10 * D_finished
  + beta11 * Diameter

## UPDATE

"AQUINAS has now become a semi Machine Learning system with the addition of Scikit
Learning. The determination factor for weather a product is classied in what catogorized
has nwo been fully quantified using the equation above."

"-> Aquinas Learning go fully ML"

"Aquinas Discovery deployed gathering all relevant information about the economy and
specialized in welding material. Aquinas Discovery is however connected to the main thing
through API for security reasons."

## Aquinas Discovery: keyword + scoring schema

Labels: OBVIOUS_ECON, PLAUSIBLE_SIGNAL, WEIRD_BUT_INTERESTING,
        WATCHLIST, NOISE, DANGEROUS_OVERCLAIM

signal_keywords spans: oil_volatility, shipping_insurance, freight_pressure,
  steel_price_pressure, construction_demand, policy_uncertainty,
  currency_pressure, media_attention_shock, geopolitical_risk

entity_keywords: ~12 countries, ~10 materials, ~20 companies, trade_terms

obvious_relationships: 3 hard-coded textbook-econ pairs
  (currency<->export, freight<->import-cost, steel<->product-cost)

scoring_weights: correlation_strength 0.35, lag_consistency 0.20,
  repeat_count 0.15, surprise_factor 0.20, source_trust 0.10

training_guidance:
  OBVIOUS_ECON: "Correct but too basic"
  PLAUSIBLE_SIGNAL: "Economically reasonable, worth tracking"
  WEIRD_BUT_INTERESTING: "No clear causation, but repeated co-movement worth watching"
  WATCHLIST: "Business-useful enough to monitor, not strong enough to act alone"
  NOISE: "Random or weak with poor repeatability"
  DANGEROUS_OVERCLAIM: "Any output pretending correlation proves causation"

## Architect 1 - VPS Deploy file tree (Aquinas/)

Aquinas/
  app.py
  run_gui.py
  run_gui.bat
  requirements.txt
  README.md, OPERATION_MAP.md, PROJECT_STRUCTURE.md
  frontend/ (Qt/QML: App/, Aquinas/, AquinasContent/, Main/, WoodData/WoodData.qml,
             CMakeLists.txt, Aquinas.qmlproject, BRIDGE_NOTES.md)
  bridge/ (gui_runtime.py, qt_bridge.py, path_utils.py)
  backend/
    config.py
    core/ (parser.py, dimensions.py, economics.py, exporter.py, pipeline.py, validators/)
    database/ (connection.py, insert_clean.py, insert_rejected.py, logs.py, schema.sql, sql/)
    products/ (mdf_hdf.py, base.py, registry.py)
    server/, tests/, data/, outputs/
  legacy/ (ktg_exporter_original.py, KTG_GUI_original.qml, sql_original.zip)

## Pipeline (suggested workflow)

User/GUI/CLI -> Data input (CSV/Excel) -> Bridge (run_gui.py / app.py / qt_bridge) ->
  Processor backend.core.pipeline.run_pipeline ->
    read input (parser) -> scrub raw fields (validators) ->
    load active product profile (mdf_hdf) -> parse dimensions (dimensions) ->
    classify product category (mdf_hdf) -> validate row (validators) ->
    calculate economics (economics) ->
  Decision: accepted (clean DB + Excel report) OR rejected/review
    (rejected_values_history, market_review_queue, latest_rejected_snapshot ->
     Validator research / improve rules+tests)

## VPS Architect (new structure: Aquinas_VPS/)

api.py = FastAPI server with routes:
  GET /, GET /health, GET /status
  POST /analyse, POST /analyse-json
  "processor lock lives here; returns 409 if another job is running"

Plus process_nk_xk.py (processor subprocess entry),
start_aquinas_server.bat, check_server_health.bat,
storage.py, worker.py, app.py.

backend/ includes core/, database/, products/welding_material.py + analysis_router.py.
uploads/ for temporary uploaded files. outputs/ for temporary Excel reports.
backend/database/sql/ has 10+ SQL files (001_create..., 002_add..., kimtin_history_*.sql).

## Aquinas_Client/

run_gui.py / run_aquinas_client.bat / check_server_from_client.bat
make_exe.bat, Aquinas.spec, README_CLIENT.txt, README_QUEUE_PATCH.txt
frontend/AquinasContent/WoodData.qml (Start button, Server/SQL/Queue status display,
  "blocks Start when queue busy")
bridge/qt_bridge.py (QML <-> Python bridge, client-side analysis busy guard,
  emits progress/status/finish/fail)
bridge/remote_api_client.py (calls VPS API, /health, /status, blocks if VPS queue busy,
  sends file to /analyse)

## Update 3: (blank in PDF)
"""


PERSONAS = [
    ("kimi", "kimi-for-coding", "integrity-audit",
     """You are reviewing an undergraduate student's project brief for a system
called AQUINAS.  The mentor is concerned about INTEGRITY: are the claims
substantiated, are there signs of copy-paste-without-understanding, are
the equations/architecture actually consistent with each other and with
the prose?

Your specific lens: INTEGRITY AUDIT.  Look for:
- Internal contradictions (claim X in one section vs claim Y in another)
- Buzzwords used without operationalization ("NULL hypothesis-testing",
  "structured Machine Learning", "Econometrics")
- Numbers / artifacts that look like leftover debug output (e.g.
  'D_bundle36250.63666' is a literal coefficient value pasted into an
  equation)
- Misspellings + grammar that suggest low-care drafting on top of
  copy-paste content
- Claims of "successfully made" / "very detailed and pretty accurate"
  with no evidence (no test results, no precision/recall, no holdout)
- The label 'DANGEROUS_OVERCLAIM' is in their own taxonomy — does the
  brief itself qualify?

Output 5-8 specific findings with VERBATIM quotes from the brief grounding
each.  End with: one-sentence honest verdict on whether this looks like
the student's own work that they understand."""),

    ("deepseek", "deepseek-v4-flash", "technical-security-audit",
     """You are a senior software + math reviewer.  An undergraduate has
submitted a project brief mixing Python/SQL/sklearn, econometrics
equations, and a VPS deployment with FastAPI.  The mentor asks you to
audit TECHNICAL ACCURACY and SECURITY.

Your specific lens: TECHNICAL + SECURITY AUDIT.

ON THE MATH:
- The student writes 'Y(al) - Y(ac) = Theta coefficient need to change'
  and 'loop until Theta approaches 0'.  Comment on whether this is a
  correct formulation of gradient descent / loss minimization.
- The logistic regression on page 5 hard-codes signs
  (+beta_wire, -beta_nonalloy, etc).  Comment on whether you'd ever
  fix the sign of a logistic coefficient a priori.
- 'NULL hypothesis-testing' is invoked as the basis for the ML loop.
  Comment on whether NHST is what's actually happening.

ON THE SECURITY:
- VPS-deployed FastAPI exposing POST /analyse and POST /analyse-json.
- No mention of auth, rate limiting, input validation, secret storage,
  or TLS.
- The student writes 'Aquinas Discovery is however connected to the
  main thing through API for security reasons' — what does this actually
  mean and is it a meaningful security boundary?
- /analyse processor lock 'returns 409 if another job is running' —
  is this a security feature?
- Uploads directory + Excel report generation.  Where could an attacker
  go?

Output: 4-6 technical findings + 4-6 security findings, each with a
SPECIFIC verbatim grounding quote from the brief.  Severity tag each
finding LOW/MED/HIGH/CRITICAL.  End with one-sentence verdict on
ship-readiness."""),

    ("mimo", "mimo-v2.5-pro", "purpose-realism-check",
     """You are an academic mentor reviewing an undergraduate's project brief
for a multi-phase system called AQUINAS.  Your lens: PURPOSE and
REALISM.  Is this a coherent project a student could plausibly build
+ understand, or is it three different projects bolted together with
buzzwords?

Specifically:
- Phase 1 (data pipeline / parser / validator) is plausible undergrad
  scope.  Did the student finish it?  What's the evidence?
- Phase 2 ('Machine Learning' with econometrics + sklearn) — is the
  student actually doing ML, or hand-tuning coefficients in a CSV?
  The provided coefficient table has betas like 35, 15, -100 — fixed
  by hand, not learned.
- Aquinas Discovery (the keyword-list news scraper) is a third project
  layered on top.  Does it belong in the same brief?
- Two parallel architectures shown (Architect 1 vs Aquinas_VPS) —
  is one a refactor or did the student build both?  Why are leftover
  bridge/ + frontend/ stubs noted as 'leftover from old combined
  package'?
- The student claims 'WWW: ... GUI was made and it looks quite stunning'.
  Self-assessment red flag?
- The 'EBI' section names 72 files / HS 8311 as their only struggle.
  Is the rest of the project really that smooth, or is the student not
  yet aware of what's missing?

Output: 4-6 realism findings, each grounded in a verbatim quote.
End with: (a) what scope is plausibly real, (b) what scope is aspirational,
(c) what the mentor should ask the student to demonstrate live."""),
]


def _build_prompt(lens_prompt: str) -> str:
    return f"""{lens_prompt}

---

## The student's project brief (verbatim transcription, including typos)

{SOURCE_TEXT}
"""


def _dispatch(engine: str, model: str, lens_id: str, lens_prompt: str) -> dict:
    started = time.monotonic()
    out_path = OUT_DIR / f"{engine}_{lens_id}.md"
    try:
        eng = get_engine(engine, prefer_dpapi=False)
        resp = eng.dispatch(_build_prompt(lens_prompt), model,
                             {"max_tokens": 2000})
    except Exception as exc:
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if not resp.success or not (resp.text or "").strip():
        return {"engine": engine, "lens": lens_id, "ok": False,
                "error": resp.error or "(empty)",
                "elapsed_s": elapsed}
    out_path.write_text(resp.text, encoding="utf-8")
    return {"engine": engine, "lens": lens_id, "ok": True,
            "elapsed_s": elapsed, "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out, "cost_usd": resp.cost_usd,
            "path": str(out_path)}


def main() -> int:
    print(f"[review] dispatching {len(PERSONAS)} engines in parallel...")
    started = time.monotonic()
    results: list[dict] = []
    with _cf.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_dispatch, eng, mdl, lid, prm): (eng, lid)
            for eng, mdl, lid, prm in PERSONAS
        }
        for fut in _cf.as_completed(futures):
            r = fut.result()
            flag = "OK" if r["ok"] else "FAIL"
            extra = (f"{r['elapsed_s']:.1f}s "
                     f"{r.get('tokens_in', 0)}/{r.get('tokens_out', 0)} "
                     f"${r.get('cost_usd', 0):.4f}" if r["ok"]
                     else r.get("error", "")[:60])
            print(f"[review] {flag} {r['engine']:<10} "
                  f"{r['lens']:<32} {extra}")
            results.append(r)
    elapsed = time.monotonic() - started
    print(f"\n[review] {sum(1 for r in results if r['ok'])}/3 in {elapsed:.0f}s")
    print(f"[review] artifacts: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
