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