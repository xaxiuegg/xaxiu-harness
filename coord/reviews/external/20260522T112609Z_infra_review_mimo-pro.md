<!-- engine=mimo model=mimo-v2.5-pro success=True latency_ms=21386 -->

# Post-Migration Smoke Assessment — 2026-05-22

## 1. Is the infrastructure now fit for autonomous dev-loop work?

**Conditional yes.** All HTTP probes pass, observer is armed and cycling cleanly (total_cycles=8), coord generates valid plans, and 1224/1224 pytest green. However, if autonomous work requires DeepSeek as a primary or targeted engine (e.g., cost-sensitive batch runs), the dispatcher will silently redirect to Kimi every time — you'll burn more tokens than budgeted and get different model behavior without an explicit error. For pure MiMo/Kimi workloads, it's ready now.

## 2. What's the #1 risk if I leave the project running unattended for 8 hours?

**Silent DeepSeek→Kimi cost overburn, ~70% likelihood if any automated task targets DeepSeek.** Every DeepSeek-typed dispatch silently falls through to Kimi (~3–5× cost per call on typical SGP token plans). Over 8 hours of observer auto-cycles or batch coord runs, this could exhaust the Kimi budget allocation while DeepSeek capacity sits unused — then Kimi starts failing too, cascading into total dispatch failure across the fallback chain with no alert until budget exhaustion.

## 3. Diagnose: DeepSeek dispatch_packet returns engine_used=kimi

The failure path is **not** in the raw HTTP layer (Cat A proves 200 OK in 1.4s). It's in `dispatch_packet`'s response-classify guard between raw HTTP response and `response.success = True`. Most likely culprits, in order:

1. **`guards.classify_response` threshold mismatch** — DeepSeek-v4-flash returns a valid 200 but the response body schema doesn't match the expected structure (e.g., missing `choices[0].message` or non-standard `finish_reason` value). The classifier scores this as `success=False` even though HTTP was fine. Fastest check: add a `logger.debug` dump of the raw response body inside `classify_response` for the `deepseek` backend path.

2. **`response.success` default is `False`** — If the DeepSeek-specific response parser raises a caught exception (JSON parse, key missing), `success` stays at its default `False` value, and the exception is swallowed silently. The fallback chain then fires normally.

3. **Guardrail / content-policy false-positive** — Less likely at 1.4s response time, but possible: the DeepSeek response contains a refusal or truncated output that the guard layer flags as failure.

**Recommended next diagnostic:** One targeted test:

```python
raw = requests.post(deepseek_endpoint, json=payload, timeout=30)
print("raw_status:", raw.status_code)
print("raw_body_keys:", list(raw.json().keys()))
resp = classify_response("deepseek", raw)
print("classified_success:", resp.success)
print("classified_error:", getattr(resp, 'error', None))
```

This narrows it to classify_response vs. the transport layer in < 30 seconds.

## 4. One-line top change to ship next

**Add a `logger.warning` in the dispatcher fallback chain that emits `{forced_engine}→{actual_engine}: classify_response returned {error_details}` whenever a `force_engine` directive is overridden, so silent redirects become visible in logs without any behavioral change.**