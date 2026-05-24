# SPEC-ID: proxy-failure-matrix — observable behavior, fail-mode, operator action

**Authored**: 2026-05-24 per W9-PROXY-FAILURE-MATRIX
(master-audit M13 PROXY-SAFETY).

The v2/A proxy at `src/harness/proxy/` is the safety-critical layer
that routes operator dispatches through a pool of API keys with
circuit-breaker + auto-quarantine semantics.  M13 flagged it as
"opaque" — zero proxy tests in the mutation kill-rate table, and
auto-quarantine-on-flap was silently non-functional for an unknown
duration before W8.

This document is the **single ground-truth contract** for what the
proxy does in every failure mode the operator might encounter.
Each row maps a failure scenario to: (a) observable behavior,
(b) whether the dispatch fails open or fails closed, (c) the
operator action required.  The companion test suite
`tests/test_proxy_failure_matrix.py` exercises each row.

## Glossary

- **Fail-open**: dispatch proceeds (possibly with reduced safety —
  e.g. degraded key, slower path).  Operator sees success.
- **Fail-closed**: dispatch refuses; the caller gets a typed error.
  Operator sees a clear failure surface.
- **Auto-quarantine**: a key with ≥3 circuit trips in a 60-min
  rolling window gets `permanent=True` set; it stays out of routing
  until the operator explicitly resets it.

## Failure-mode matrix

| # | Failure mode | Observable behavior | Fail mode | Operator action |
|---|---|---|---|---|
| 1 | **Single key revoked** (401/403 on one of N) | `classify_outcome` -> `auth_failure`; circuit opens after `consecutive_failures` threshold; `pick_key` skips this key. | **Fail-open** — other keys still serve. | Rotate the revoked key in DPAPI; `harness proxy unquarantine <alias>` if needed. |
| 2 | **All keys revoked** | Every key's circuit opens; `pick_key` returns `None`; dispatch caller sees no routable key. | **Fail-closed** — dispatch refuses. | Rotate all keys in DPAPI; restart the proxy or wait for the cooldown windows. |
| 3 | **Circuit-breaker open on every key** | `pick_key` returns `None` because no key satisfies `is_routable`. | **Fail-closed** — dispatch refuses. | Wait for `cooldown_until` (default 60s after a trip); or `harness proxy unquarantine` to force-close circuits. |
| 4 | **All keys exhausted (in-flight saturation)** | All keys at `in_flight >= max_concurrent`; `pick_key` returns `None` even though circuits are CLOSED. | **Fail-closed** — dispatch refuses. | Increase `max_concurrent` per key; wait for in-flight to drain; or add more keys to the pool. |
| 5 | **All engines quarantined** (downstream engine_health, not proxy) | Proxy still routes if keys are healthy, but the dispatcher's pre-flight check refuses based on `engine_health` state. | **Fail-closed** — dispatcher refuses before the proxy. | `harness engines heal` to recover keys; `harness engines reset <engine>` to manually unquarantine. |
| 6 | **TLS handshake failure** (upstream cert/cipher problem) | `classify_outcome` -> `server_error` (exception type doesn't match timeout names); circuit opens after consecutive failures. | **Fail-open** — other keys retry. | Investigate upstream CA bundle; ensure system clock is correct; circuit recovers automatically. |
| 7 | **Upstream timeout** (request exceeds wall-clock) | `classify_outcome` -> `timeout`; transitions toward circuit-open. | **Fail-open** — fallback engine attempted. | If pattern persists, inspect upstream provider status; consider reducing `--max-tokens`. |
| 8 | **Rate-limit (429)** | `classify_outcome` -> `rate_limit`; circuit may open if sustained. | **Fail-open** — fallback engine. | Tighten dispatch concurrency or upgrade the API plan. |
| 9 | **Schema violation (422)** | `classify_outcome` -> `schema_violation`; does NOT trip circuit by default (it's a payload issue, not a key issue). | **Fail-open** — caller's responsibility to fix the packet. | Fix the packet (escape characters, max-tokens, model name) and re-dispatch. |
| 10 | **Flap detection** (≥3 trips in 60min) | `_detect_flap` returns True; `transition` sets `permanent=True` + `auto_quarantined_at=now`; key drops out of routing pool permanently until reset. | **Fail-open** — other keys serve. | Investigate root cause (rotated key not synced?); `harness proxy unquarantine <alias>` to re-enable. |
| 11 | **Proxy state file corrupt** | `read_state` raises `ValidationError` or `JSONDecodeError`; proxy refuses to start. | **Fail-closed** — proxy doesn't start. | Restore `state/proxy_state.json` from backup; or delete it and re-init. |
| 12 | **Proxy process killed mid-write** | W9-STATE-ATOMIC-WRITES temp+rename guarantees the original state file is never half-written. | Recoverable on restart. | None. Proxy resumes from last good state. |

## Auto-quarantine semantics (load-bearing)

The auto-quarantine-on-flap behavior was the defining safety feature
that W8 found broken; the regression matters and merits its own row.

- `circuit_trip_history` records ISO timestamps each time the circuit
  transitions to OPEN.  Cap at 20 entries.
- `_detect_flap(state, now)` returns True iff ≥3 entries fall within
  a 60-minute rolling window ending at `now`.
- When detected, `transition` sets `state.permanent = True` and
  `state.auto_quarantined_at = now.isoformat()`.
- Quarantined keys are excluded from `pick_key` until the operator
  explicitly clears `permanent` via `harness proxy unquarantine
  <alias>`.

## What this matrix doesn't cover

- **DPAPI seed failure** — handled by `harness env`, not the proxy.
- **DNS resolution failure** — classified as `server_error`.
- **Operator misconfig** — wrong base URL, wrong model name in
  packet → mostly surfaces as 4xx; not in scope of proxy-side
  failure handling.

Anything that surfaces a failure mode NOT in this matrix should be
filed as a Wave 10 candidate.
