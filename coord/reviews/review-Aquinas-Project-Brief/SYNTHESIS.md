# Multi-engine review: Aquinas Project Brief.pdf

**Generated**: 2026-05-25T00:25Z
**Document**: `D:\Download\Downloads\Aquinas Project Brief.pdf`

**Lenses dispatched**:
- `technical-and-security` via **deepseek** (20s, 6522/2239 tokens, $0.0000) — OK
- `purpose-and-realism` via **mimo** (32s, 6455/1643 tokens, $0.0000) — OK
- `correctness-and-integrity` via **kimi** (245s, 6099/7950 tokens, $0.0000) — OK

**Total cost**: $0.0000 (3/3 engines succeeded)

---

## Per-lens reviews

### technical-and-security (via deepseek)

## Technical Findings

1. **Oversimplified and likely non-convergent ML training loop**  
   The “learning” logic relies on iteratively adjusting coefficients until “theta approaches 0”, but no gradient descent, loss function, or convergence criteria are defined. This is manually tuned ad‑hoc and will not generalize.  
   **Severity: HIGH**  
   *Quote: “Y(al) - Y(ac) = Theta coefficient need to change. This process would be looped over and over again, until the change of coefficient is approaching 0”*

2. **Spaghetti MySQL update function identified as a known blocker**  
   The author admits the database update logic is unmaintainable and hasn’t been refined, risking inconsistent state and data corruption during concurrent updates.  
   **Severity: HIGH**  
   *Quote: “The MySQL updating function is still too spaghetti and needed to be refined.”*

3. **No validation or handling for missing data in two critical datasets**  
   The system relies on 72 and 8311 data sets that have many missing fields, yet no imputation, fallback, or robust error handling is described. The move to ML is stated as a future solution, not implemented.  
   **Severity: MEDIUM**  
   *Quote: “due to the fact that these two data sets have a lot of missing factors that lead to the automation process becoming harder and harder.”*

4. **Econometric model may suffer from multicollinearity and arbitrary signs**  
   The logistic regression uses highly correlated dummy variables (e.g., `D_wire`, `D_alloy`, `D_rod`, `D_finished`) with coefficients forced to negative signs (`−β6` etc.), likely causing unstable estimates and overfitting.  
   **Severity: MEDIUM**  
   *Quote: “P(Yi =1 ∣ Xi ) = Λ(β0 + β1 Dwire,i + β2 Dalloy,i +… − β6 Dnonalloy,i − β7 Dwelding,i …)”*

5. **Version control and reproducibility gaps**  
   Coefficients are stored in MySQL but there is no mechanism to lock or reproduce a specific model state; runs can silently pick up different coefficient versions, breaking audit trails.  
   **Severity: MEDIUM**  
   *Quote: “coefficient_versions - coefficient_version - factor_name - product_type - coefficient_value - active_status”* (no mention of freeze or reproducible run logic)

6. **Hard‑coded thresholds and no automated hyper‑parameter tuning**  
   The initial rules are “set by absolute constant” and trialled manually, with no cross‑validation or automated parameter search, making the system fragile to data drift.  
   **Severity: LOW**  
   *Quote: “Rules are still set by absolute constant. Through trial and error.”*

---

## Security Findings

1. **No authentication on any API endpoint**  
   The FastAPI endpoints (`/analyse`, `/analyse-json`, `/health`, `/status`) lack any form of auth, allowing any external actor to submit files, query status, or potentially exhaust server resources.  
   **Severity: CRITICAL**  
   *Quote: “Aquinas_VPS/ ├── api.py # FastAPI server │ … GET / │ GET /health │ GET /status │ POST /analyse │ POST /analyse-json”* (no auth middleware described)

2. **Unsanitised file uploads enabling DoS and injection attacks**  
   The system accepts CSV/Excel uploads without content‑type validation, size limits, or filename sanitisation. An attacker could upload a malicious Excel macro file or CSV with embedded formulas.  
   **Severity: HIGH**  
   *Quote: “Data input - CSV - Excel - future uploaded/server file”* and *“uploads/ └── .gitkeep # temporary uploaded files”*

3. **Lack of TLS (HTTPS) for client‑server communication**  
   The client connects to the VPS API over plain HTTP (`remote_api_client.py`), exposing uploaded data and status responses to network interception.  
   **Severity: HIGH**  
   *Quote: “remote_api_client.py # calls VPS API │ … sends file to /analyse”* (no mention of HTTPS or certificates)

4. **SQL injection risk in legacy “spaghetti” database code**  
   The acknowledged “spaghetti MySQL updating function” and raw SQL migration files strongly suggest no parameterised queries, making SQL injection possible through any user‑supplied field (e.g., file names, row data).  
   **Severity: HIGH**  
   *Quote: “The MySQL updating function is still too spaghetti and needed to be refined.”* (indicates dynamic SQL construction without sanitisation)

5. **No input validation on the processor’s uploaded file path**  
   The `/analyse` endpoint likely writes uploaded files to a local directory, but no path traversal checks are documented. An attacker could supply a crafted filename to overwrite arbitrary files.  
   **Severity: MEDIUM**  
   *Quote: “├── uploads/ └── .gitkeep # temporary uploaded files”* (no sanitisation or isolation described)

6. **Processor lock race condition and denial of service**  
   The API uses a single “processor lock” to serialise analyses; if the lock is held indefinitely (e.g., by a crashed job), all subsequent valid requests are blocked with a 409, enabling a trivial DoS.  
   **Severity: MEDIUM**  
   *Quote: “processor lock lives here │ returns 409 if another job is running”* (no timeout or stale‑lock recovery mentioned)

---

## Ship‑Readiness Verdict

**NOT READY** — The system lacks fundamental security controls (authentication, TLS, input sanitisation) and contains critical technical flaws in its ML training loop and database architecture, both of which would lead to unreliable results and expose the VPS to immediate compromise.

### purpose-and-realism (via mimo)

**Realism & Scope Review: Aquinas Project Brief**

Here are 6 realism findings based on the provided brief:

1. **Plausible Data Engineering Foundation**
   *Verbatim:* "Accurately filter out information from the trade data set through pipelines, validators and parser using Python, SQL, Pandas"
   *Assessment:* This is a solid, classic data engineering task. Using Pandas for data wrangling and SQL for storage is standard and credible. The mention of a specific, complex project structure (e.g., `backend/core/validators`, `backend/products/`) suggests a well-planned, modular architecture that is plausible to build.

2. **Vague but Directionally Correct ML Concept**
   *Verbatim:* "Y(al) - Y(ac) = Theta ... This process would be looped over and over again, until the change of coefficient is approaching 0"
   *Assessment:* This describes a basic iterative optimization process (like gradient descent) for adjusting model coefficients. The intent is sound. However, the preceding explanation conflating econometrics with "if→then" rules ("the binary concept of 0 and 1") is muddled. The project's later use of logistic regression (`P(Yi=1 | Xi) = Λ(...)`) is a correct and standard supervised learning technique for classification.

3. **Highly Aspirational "Aquinas Discovery" Scope**
   *Verbatim:* "Aquinas Discovery deployed gathering all relevant information about the economy and specialized in welding material... connected to the main thing through API for security reasons."
   *Assessment:* This represents a major scope leap. Building a real-time macroeconomic signal detector (with keyword scraping, entity extraction, and relationship mapping) is a separate, full-scale research project. Connecting it via API is possible, but the described system—analyzing "breaking news," "war risk premium," etc.—is vastly more complex than the core trade data classifier and reads as aspirational.

4. **Plausible Client-Server Architecture**
   *Verbatim:* "VPS version is deployed and the GUI was made and it looks quite stunning. Client and Server coding work somewhat coherently together."
   *Assessment:* The described architecture (FastAPI backend on a VPS, separate QML/Python client that calls the API) is modern and realistic. The mention of specific files like `api.py` (FastAPI), `remote_api_client.py`, and queue management (`409 if another job is running`) shows a practical understanding of building a deployable web service with a remote frontend.

5. **Overly Ambitious Integrated Vision**
   *Verbatim:* "The MySQL updating function is still to spaghetti and needed to be refined... The solution I had for this is to slowly but steadily move from Human factor → Machine Learning concept."
   *Assessment:* This reveals the author's grand vision: to replace manual data cleaning with an automated, learning system. While the *goal* is logical, the brief jumps from a working Phase 1 pipeline to a complex, self-improving ML model and a separate economic discovery engine. For a single developer or small team, this scope—spanning robust data engineering, ML model training/deployment, GUI development, and macroeconomic research—is extremely ambitious and risks being "stitched together" at the seams.

6. **Credible Domain-Specific Detail**
   *Verbatim:* "72 8311 = finished welding consumables: coated electrodes, cored wire, coated rods, etc." and the `WELDING_GROUP` list.
   *Assessment:* The inclusion of specific HS codes, industry terminology, and a concrete product taxonomy indicates genuine domain knowledge in the target field (trade, flooring, welding materials). This grounds the project in a real-world problem, which is a strong point for plausibility.

---

**(a) What's Plausibly Real:**
*   The core **data processing pipeline** (parsing, validating, cleaning trade CSVs/Excel files) with a well-structured Python/SQL backend.
*   The **client-server architecture** with a FastAPI backend on a VPS and a separate GUI client.
*   The **initial ML/Classification model** using **logistic regression** (as shown in the equation on page 5) to categorize items like flooring or welding wire. The iterative coefficient adjustment loop is a valid ML training concept.

**(b) What's Aspirational:**
*   The **"Aquinas Discovery"** module acting as a real-time economic signal analyzer. This is a separate, research-heavy project.
*   The vision of the system **autonomously moving from "Human factor → Machine Learning,"** implying a fully self-improving system without clear boundaries on how errors are corrected and models retrained.
*   The implied **breadth of coverage**—from flooring to welding to macroeconomic trends—within a single, coherent system.

**(c) What to Ask the Author to Demonstrate Live:**
1.  **Show the ML Loop:** Demonstrate the live process: import a dataset, run it through the classifier, have the system flag errors, manually correct them (creating the `correct_truth_sheet`), re-run the training to adjust coefficients, and show the accuracy metric (Theta) improving.
2.  **Demo the Full Stack:** Start the VPS API, launch the client GUI, upload a sample trade file, and show it being processed, the results displayed, and the report generated—all through the client-server flow.
3.  **Explain the Coefficient Adjustment:** Pick one coefficient (e.g., `β₆ D_nonalloy`). Show where its current value is stored (MySQL), explain exactly how the error analysis updates it (the math/logic), and show how the system applies the new value in the next run.

### correctness-and-integrity (via kimi)

1. **Math error in logistic regression formulation**: The conditional-probability equation incorrectly places the error term εᵢ inside the logistic function Λ(·). In a standard logit model the error belongs to the latent-variable formulation, not inside P(Y=1|X), and the dummy variable `D_suspected_welding` is fractured by a spurious line break.  
   > `P(Yi =1 ∣ Xi )= Λ(β0 +β1 Dwire,i + β2 Dalloy,i + β3 Dcoil,i + β4 Dspool,i + β5 Dbundle,i − β6 Dnonalloy,i − β7 Dwelding,i − β8 Ds`  
   > `uspected_welding,i −`  
   > `β9`  
   > `Drod,i −`  
   > `β10`  
   > `Dfinished,i +`  
   > `β11`  
   > `Diameteri +`  
   > `ε`  
   > `i )`

2. **Debug artifact / numeric value leaked into a variable name**: In the linear-score equation for HS code 7229 the dummy variable `D_bundle` is concatenated with the number `36250.63666`, as if a coefficient or cell value was accidentally pasted into the variable identifier.  
   > `Score_7229  =  β ₀  +  β ₁ D_wire  +  β ₂ D_alloy  +  β ₃ D_coil  +  β ₄ D_spool  +  β  ₅ D_bundle36250.63666  -  β ₆ D_nonalloy  -  β ₇ D_welding  -  β ₈ D_suspected_welding  -  β ₉ D_rod  -  β ₁₀ D_finished  +  β ₁₁ Diameter   ‘’`

3. **Internal contradiction in the definition of Theta**: The text first calls Theta the “change suggested change of coefficient,” but then defines it as the output discrepancy `Y(al) − Y(ac)`, conflating a parameter-update step with the prediction error.  
   > `Theta here is the change  suggested  change  of  coefficient  within  the  model  Y  =  B0  ….  .`  
   > `Y(al)  -  Y(ac)  =  Theta   coefficient  need  to  change.`

4. **Symbol definitions copied but never used**: The document introduces γ for continuous effects and δ for interaction effects, yet the subsequent econometric equation uses only β coefficients for every term (including continuous and interaction-less variables), suggesting a template was copied without alignment to the actual model.  
   > `β   =  effect  of  dummy  feature  j  γ   =  effect  of  continuous  measurement  variable  m  δ ₐ ᵦ  =  interaction  effect  between  two  detected  features  Λ  =  logistic  function`

5. **Reference to a non-existent equation**: The author writes “as you can see in the equation above essentially Y,” but no equation precedes this statement in the document; the equation appears only later, indicating broken copy-paste ordering.  
   > `Lets  say  as  you  can  see  in  the  equation  above  essentially  Y.`

6. **Invalid JSON syntax in configuration snippet**: The `identity` block contains a trailing comma after `"AquDis"`, which makes the JSON structurally invalid and suggests unvalidated copy-paste into the brief.  
   > `{    "identity": {      "name": "AquDis",    },  "labels": [`

7. **Copy-paste directory-tree duplication**: The project-structure section repeats the directory name `Aquinas_Client/` on two consecutive lines before listing contents, a clear formatting or copy-paste slip.  
   > `Aquinas_Client/`  
   > `Aquinas_Client/  ├──  run_gui.py                        #  starts  desktop  GUI`

**Verdict:** The brief is technically unreliable, exhibiting fundamental misunderstandings of logistic regression, contradictory definitions of its own optimization variables, and numerous copy-paste artifacts that strongly suggest the author has not rigorously validated the mathematics, code, or configuration details presented.

---

## Cross-engine notes

Read each lens above for the engine-specific findings.  Look for **convergent findings** (flagged by 2+ lenses) — those carry the strongest signal.  **Divergent findings** (flagged by only one lens) are often the most novel but should be verified against the document independently.
