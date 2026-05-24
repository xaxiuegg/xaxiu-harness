<!-- name=M15-DASHBOARD-UX latency_ms=22038 error='' -->

## Score

| Row | Score | Justification |
|---|---|---|
| **Correctness** | 2 | Dashboard is invoked exactly once (`harness dashboard-serve`) — zero visibility into what it renders, which APIs it hits, or whether it matches the operator's mental model. Correctness is unassessable. |
| **Robustness** | 2 | WebSocket at 7878 with no mention of reconnect handling, backpressure, or stale-state detection. `harness today` shows live engine warnings but no indication the dashboard mirrors this state. |
| **Operator-usability** | 3 | CLI surface (`today`, `doctor`, `engines-heal`) is well-designed for non-technical use. But the dashboard — the *visual* operator surface — has zero documented UX flow. Non-technical operator will likely ignore it. |
| **Test discipline** | 1 | No dashboard API tests, no WebSocket integration tests, no schema contract tests for `/v2/*` endpoints. The 1576 tests cover engine/coord/audit logic but not the presentation layer. |
| **Risk** | 4 | A cost panel the operator can't read is worse than none — it creates false confidence. If the dashboard silently drops WebSocket updates during an engine-dead event, the operator learns about it from CLI, not the thing they're staring at. |

## Top blocker

Ship a **one-page dashboard UX spec**: what each panel shows (status, cost, escalations, engine health), the /v2/* contract, and a screenshot/mockup. Without it, the dashboard is a code artifact nobody audits because nobody can articulate what it *should* do. This single doc would lift Correctness + Test discipline by ≥1 each.

## Verdict

**HOLD for dashboard scope.** The CLI operator surface is production-grade; the dashboard is an invisible, untested, undocumented black box running on a non-technical operator's machine. Ship the CLI; freeze dashboard until a reviewer can actually evaluate what it surfaces.
