# Technical + Security Audit of the AQUINAS Project Brief

## Technical Findings

### 1. Misrepresentation of gradient descent (HIGH)
**Verbatim quote:** *"Y(al) - Y(ac) = Theta coefficient need to change"* and *"loop 'until Theta approaches 0'"*  
**Issue:** The student treats the prediction error directly as a coefficient update term, with no learning rate, gradient, or loss function. This is not gradient descent—it is an ad‑hoc error‑driven adjustment that cannot converge reliably or generalize.

### 2. A priori sign fixing in logistic regression (MEDIUM)
**Verbatim quote:** *"Score_7229 = beta0 + beta1 * D_wire … - beta6 * D_nonalloy - beta7 * D_welding …"*  
**Issue:** Hard‑coding the sign (±) of logistic coefficients assumes the direction of influence is known in advance, contradicting the purpose of estimation. Coefficients should be learned from data without sign constraints.

### 3. Conflation of NULL hypothesis testing with ML learning loop (LOW)
**Verbatim quote:** *"NULL hypothesis - testing"* and *"reviewing their own mistakes (NULL hypothesis - testing)"*  
**Issue:** The described loop compares predictions to human labels—this is simple supervised error feedback, not Null Hypothesis Significance Testing (NHST). The term is used incorrectly but does not affect the logic.

### 4. Coefficient table with static integer values contradicts “machine learning” (HIGH)
**Verbatim quote:** Coefficient table showing `flooring_text 35 FALSE`, `no_flooring_text -35 FALSE`, etc.  
**Issue:** The “Aquinas_Learning” loop implies coefficients are updated based on errors, yet the table contains fixed integers and a `hard_rule` flag. No evidence of automated learning; the loop appears to be manual coefficient tweaking.

### 5. Linear score without logistic transformation (MEDIUM)
**Verbatim quote:** *"Lambda = logistic function"* but the implementation only computes a linear score: *"Score_7229 = beta0 + … - beta10 * D_finished + beta11 * Diameter"*  
**Issue:** A logistic regression requires applying the sigmoid to the linear combination to produce probabilities. The brief never applies `Lambda()`, so the model is actually a linear discriminant, not a properly specified logit.

### 6. “Semi Machine Learning” with Scikit‑Learn but no training or estimation (MEDIUM)
**Verbatim quote:** *"AQUINAS has now become a semi Machine Learning system with the addition of Scikit Learning"*  
**Issue:** The brief provides no code or description of using `sklearn` to train a model. The coefficient table remains hard‑coded; there is no evidence of calling `LogisticRegression().fit()` or similar. The sklearn integration is claimed but not demonstrated.

---

## Security Findings

### 1. Unauthenticated API endpoints exposing business logic (CRITICAL)
**Verbatim quote:** *"api.py = FastAPI server with routes: GET /, GET /health, GET /status POST /analyse, POST /analyse-json"*  
**Issue:** There is zero mention of authentication, API keys, or OAuth. Any attacker can call `/analyse` and `/analyse-json` to inject data or extract predictions, and `/status