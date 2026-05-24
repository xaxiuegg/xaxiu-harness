# AQUINAS Project Brief — Realism Review

---

## Finding 1: "Machine Learning" Is Hand-Tuned Rule Coefficients

> *"Absolute coefficients were set. Rules are still set by absolute constant. Through trial and error."*
>
> *"Fine tuning by hands"*

The student's own words reveal the mechanism: someone (the student) picks integer weights by trial and error. The coefficient table confirms this — betas are clean integers (35, 15, −100, −90, −80) with no decimal precision, no training procedure, no loss curve, no validation split. The −100 and −90 values for `sample_display`, `packaging_use`, and `missing_product` are labeled `hard_rule: TRUE`, which means they are effectively binary kill-switches, not learned parameters. Calling this "Machine Learning" and invoking a logistic model does not make it so. The student is doing **rule-based classification with manually weighted scoring** — which is a perfectly respectable undergraduate project, but it is not what Phase 2 claims to be.

---

## Finding 2: The Econometrics Formulation Is Decorative, Not Functional

> *"P(yi=1|Di,Zi) = Lambda(beta0 + sum_j beta_j * D_ji + sum_m gamma_m * Z_mi + sum_{a,b} delta_ab * (D_ai * D_bi))"*
>
> *"Aquinas_Learning ML loop: Y(al) = F(X)... Y(al) - Y(ac) = Theta coefficient need to change, loop 'until Theta approaches 0'"*

The probit/logit formulation is textbook material — well transcribed, but there is no evidence it is implemented anywhere. The "loop until Theta approaches 0" description lacks a convergence threshold, a learning rate, a loss function, or any indication of what library runs it. The UPDATE vaguely references "the addition of Scikit Learning" but provides zero sklearn artifacts: no model class, no `.fit()`, no hyperparameters, no cross-validation. The equation for `Score_7229` contains a term `D_bundle36250.63666` — a data value that has leaked into a variable name, almost certainly a copy-paste artifact from a spreadsheet into the document. This is someone who has *read about* logistic regression and gradient descent, not someone who has *applied* them.

---

## Finding 3: Aquinas Discovery Is a Separate Project Bolted On

> *"Aquinas Discovery deployed gathering all relevant information about the economy and specialized in welding material. Aquinas Discovery is however connected to the main thing through API for security reasons."*

A keyword-scoring news scraper with labels like `OBVIOUS_ECON`, `DANGEROUS_OVERCLAIM`, and scoring weights (`correlation_strength 0.35`, `surprise_factor 0.20`) is a fundamentally different application from a trade-data row classifier. It has different data sources (news feeds vs. CSV/Excel trade records), different output types (signal labels vs. accept/reject decisions), and different evaluation criteria. "Connected through API for security reasons" is a non-sequitur — API connectivity does not establish that two systems belong in the same project brief. The three hard-coded "obvious_relationships" (`currency<->export`, `freight<->import-cost`, `steel<->product-cost`) suggest a prototype at best, not a deployed analytical tool.

---

## Finding 4: Two Architectures Reflect Rewrite History, Not Deliberate Design

> *"leftover from old combined package"* (noted on bridge/ and frontend/ stubs)
>
> *legacy/ (ktg_exporter_original.py, KTG_GUI_original.qml, sql_original.zip)*

The project contains **three** structural variants: (1) Architect 1 — a monolithic Qt/QML desktop app with direct MySQL, (2) Aquinas_VPS — a FastAPI server with a thin client, and (3) a `legacy/` folder preserving the originals. The existence of `BRIDGE_NOTES.md`, the comment about "leftover" stubs, and files