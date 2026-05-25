# Multi-engine review: mimo-investigation-report.md

**Generated**: 2026-05-25T04:20Z
**Document**: `D:\xaxiu-harness-standalone\coord\reviews\mimo-investigation-report.md`

**Lenses dispatched**:
- `readability-and-architecture` via **mimo** (1s, 0/0 tokens, $0.0000) — FAIL
- `security-and-injection` via **deepseek** (32s, 2501/3090 tokens, $0.0000) — OK
- `bugs-and-edge-cases` via **kimi** (121s, 2436/8000 tokens, $0.0000) — OK

**Total cost**: $0.0000 (2/3 engines succeeded)

---

## Per-lens reviews

### readability-and-architecture (via mimo)

_Engine returned an error: engine returned empty/error: HTTP 400_

### security-and-injection (via deepseek)

## Security Review: `mimo-investigation-report.md`

The document is a technical investigation report describing MiMo API failures, including code analysis, test scripts, and hypotheses. I reviewed it for the specified security issue types: **SQL injection**, **command injection**, **path injection**, **format-string injection**, **unsafe deserialization**, **missing input validation**, **secret leakage**, and **missing auth checks**. No explicit instances of classic injection or deserialization vulnerabilities were found in the code snippets or descriptions. However, the following security-relevant weaknesses were identified.

---

### Finding 1: Bare `except Exception` Hides Error Details (Observability Weakness)

**Location:** `src/harness/engines/concrete.py` line 676–682  
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

**Type:** Missing input validation / insufficient error handling  
**Severity:** Medium  

**Description:**  
The exception handler swallows **all** exceptions and returns a generic `"internal"` string. This effectively erases the original exception type and message. From a security perspective, this can mask attempts to probe the system (e.g., sending malformed inputs that trigger HTTP errors, timeouts, or injection-related exceptions). An attacker who triggers a controlled error (e.g., a path traversal that results in an `OSError`) would see only `"internal"`, making detection and forensic analysis much harder.

**Risk:**  
- Loss of visibility into attack attempts.  
- Inability to distinguish between transient service issues and malicious input.  
- Could hide other security-critical exceptions (e.g., authentication failures, parameter tampering).

**Recommendation:**  
Catch explicit exception types (e.g., `httpx.HTTPStatusError`, `httpx.TimeoutException`, `httpx.RemoteProtocolError`) and include the original exception’s representation (e.g., `repr(exc)`) in the error field. Never use a bare `except Exception` that discards the cause.

---

### Finding 2: Bypassing the Wrapper for Testing Circumvents Security Controls

**Location:** `scripts/investigate_mimo_failures.py` (described in Section 2b)  
> “I wrote `scripts/investigate_mimo_failures.py` to bypass the `MimoEngine` wrapper with raw `httpx.Client` calls”

**Type:** Missing auth checks / missing security middleware  
**Severity:** Medium  

**Description:**  
The investigator deliberately bypassed the production `MimoEngine` wrapper to get raw error messages. While this is a legitimate debugging technique, it highlights that the wrapper is the **sole enforcement point** for authentication, rate limiting, logging, and input validation. Any code path that uses raw `httpx.Client` (even temporarily) can evade these controls, potentially allowing unauthorized API access or infinite retries.

**Risk:**  
- If the wrapper includes authentication (e.g., injecting an API key), a raw client call would fail or leak credentials in the clear.  
- Bypass of rate limiting could lead to accidental or intentional abuse.  
- Inconsistent security posture between “test” and “production” code paths.

**Recommendation:**  
The wrapper should remain the only way to interact with the MiMo API. If debugging is required, the wrapper should expose a debug mode that preserves exception details without sacrificing security controls. Alternatively, ensure that the raw client calls are only possible in isolated, non-production environments.

---

### Finding 3: Lack of Input Sanitization for Prompt Content

**Location:** Throughout the test matrix (Section 2b–2d)  
**Type:** Missing input validation  
**Severity:** Low (potential for prompt injection)  

**Description:**  
The report describes sending various prompts to the MiMo API, but does not mention any sanitization or validation of prompt content before dispatch. While prompts are often considered “safe” because they are generated internally, if any prompt text originates from external user input (e.g., a web form or third-party tool), **prompt injection** becomes possible. An attacker could embed commands that alter the model’s behavior or exfiltrate sensitive data through the response.  

This is also relevant if the model’s output is later used in a shell command, SQL query, or format string – the report does not describe downstream processing, but such cascading injection is a common risk.

**Risk:**  
- Prompt injection could lead to unintended model outputs, social engineering, or data leakage.  
- If output is naively fed into other systems (e.g., `os.system()` or `eval()`), command injection may occur.

**Recommendation:**  
Always treat prompt content as untrusted if any part comes from outside the harness. Apply strict input validation (length, allowed characters, format). For sensitive operations, use parameterized APIs (e.g., structured data instead of raw strings) and separate instructions from user data.

---

### Summary Table

| Finding                                                        | Type                        | Severity | Affects (listed types)                     |
|----------------------------------------------------------------|-----------------------------|----------|--------------------------------------------|
| 1. Bare `except Exception` hides errors                        | Missing input validation    | Medium   | – (indirectly masks injection attempts)    |
| 2. Bypassing wrapper for testing                               | Missing auth checks         | Medium   | Auth, logging, rate-limiting               |
| 3. No prompt sanitization                                      | Missing input validation    | Low      | Potential injection (prompt, command, SQL) |

---

### Additional Notes

- **Secret leakage:** The report does not reveal any API keys, passwords, or tokens. However, if the harness stores secrets in source code or configuration exposed in logs, that would be a separate High severity finding – not present here.  
- **Unsafe deserialization:** Not observed. The only data handling is JSON API responses (assumed safe).  
- **Format-string / path injection:** Not present in the provided snippets. The file paths referenced are static strings.

**Overall Security Posture:** The codebase exhibits two medium-severity weaknesses that degrade observability and security consistency. The bare exception handler is the most impactful; fixing it would significantly improve the ability to detect and respond to attacks. Prompt injection risk is low in the current context but should be addressed if the system evolves to accept external input.

### bugs-and-edge-cases (via kimi)

Here is a senior-level review of the investigation report, the referenced code, and the experimental methodology.

---

**Severity: HIGH**
**Location:** `src/harness/engines/concrete.py:676`
**Problem:** Bare `except Exception:` swallows the real exception, remaps it to the opaque string `"internal"`, emits no logs, and captures no traceback. This makes production incidents undebuggable and directly caused the misdiagnosis that led to this investigation.
**Fix:** Catch specific `httpx` exceptions (`HTTPStatusError`, `RemoteProtocolError`, `ConnectError`, `TimeoutException`). Use `logger.exception("MiMo dispatch failed")` inside the handler. Store the original `repr(exc)` in the `error` field (e.g., `error=f"{type(exc).__name__}: {exc}"`). If the exception is not a known transient network error, re-raise after logging.

---

**Severity: HIGH**
**Location:** `scripts/investigate_mimo_failures_round2.py` (implied by report §2c)
**Problem:** T12-50KB and T12-75KB each failed once and were attributed to "server load variance." Single-shot failures on a black-box remote service are insufficient to distinguish deterministic thresholds from transient node noise, cold-start penalties, or routing to an unhealthy backend.
**Fix:** For every failed configuration, immediately retry the *exact* same request 2–3 times sequentially. Capture response headers (`x-request-id`, `Server`, etc.) on both success and failure. Only classify a boundary as "variance" if the outcome is inconsistent across retries.

---

**Severity: MED**
**Location:** `src/harness/engines/concrete.py:676` (context not fully shown)
**Problem:** The `except` block references `start`. If `start = time.monotonic()` is defined *inside* the `try` block and an exception occurs before that line (e.g., during request payload serialization), the handler itself will raise `UnboundLocalError`, replacing the root cause with a secondary crash.
**Fix:** Move `start = time.monotonic()` to immediately before the `try` block so the variable is always defined in the exception handler.

---

**Severity: MED**
**Location:** `src/harness

---

## Cross-engine notes

Read each lens above for the engine-specific findings.  Look for **convergent findings** (flagged by 2+ lenses) — those carry the strongest signal.  **Divergent findings** (flagged by only one lens) are often the most novel but should be verified against the document independently.
