<!-- engine=mimo model=mimo-v2.5-pro success=True latency_ms=34025 tokens_in=16869 tokens_out=1570 persona=architect -->

# Review by Software Architect

# Architecture Review: xaxiu-harness Session 2026-05-23

## Top 3 Concerns

### 1. Engine Adapter Proliferation Without Shared Grammar Contract

Every engine has bespoke SSE parsing, error taxonomy, and token extraction baked directly into `concrete.py`. Kimi's bugs (W5-V: missing `stream:true`, non-standard `data:{` vs `data: {`, missing `import json`) weren't flukes — they're symptoms of each adapter reimplementing the same concerns slightly differently. MiMo has its own SGP endpoint quirks. DeepSeek had its own `"thinking": false` rejection (W2-INFRA-SMOKE fix). With the operator asking for 10+ engines eventually, `concrete.py` will become a 2000-line god file.

**Missing abstraction**: An `EngineTransport` protocol that standardizes SSE parsing, chunk reassembly, and `EngineResponse` population — with per-engine only overriding *connection params* and *payload shape*, not the streaming loop. The W5-V Kimi fix touched ~80 lines of streaming logic that should have been shared infrastructure.

### 2. Token Tracking Is Ghost Infrastructure

W4-K wired `response.usage → EngineResponse`, yet "every ledger row shows in=0 out=0" persists across two context resets. This means W5-D (budget by-run cost rollup) and the reliability digest (W5-C) are publishing dashboards built on zeros. The operator doesn't know they're seeing fabricated data. This is the kind of bug that erodes trust silently — you don't discover it until a budget decision goes wrong. **W4-K shipped without end-to-end validation against a real API call that returns usage data.** That's a process failure: the commit message says "wire token tracking" but no integration test proves the wires carry current.

### 3. Hook Noise Drowned the Session

Operators #8–31 are the *same stale-STATUS.csv hook* firing on cross-project warehouse files that have nothing to do with harness development. That's 24 stop-hook interruptions in a single session, each consuming operator attention and assistant tool calls. The hook `check-csv-stale.sh` lives in `D:/Projects/warehouse/.claude/hooks/` but fires based on *any* recently-modified file in that workspace tree. The harness migrated to a standalone folder (W2-MIGRATION-STANDALONE) but the hook's scope wasn't updated. This is a **post-migration hygiene debt** that will recur every session until the hook is scoped to its own project or disabled for the harness context.

## What Was Done Right

**Silent-no-op bilateral guard (W4-A + W4-B)** is excellent defensive architecture. Worker reports "completed" but edited zero files? Fail it. Integrator merged zero workers? Fail it. This is the kind of defense-in-depth that prevents 3am "why is the overnight run empty" disasters. The sister-fix pattern (finding the same class of bug on both sides of the pipeline and fixing both) shows real systems thinking.

**bypass_chain + visibility warning (W3-A)** — clean API design. The kwarg preserves the default fallback chain while offering an escape hatch, and the WARNING log on the success path when `force_engine != engine_used` catches silent substitution before it becomes mystery behavior. Steal this pattern for every override-able default.

**The 20-agent brainstorm architecture** (4 engines × 5 FUTs each) is a genuinely novel testing strategy — using the multi-engine dispatch itself as a test harness for the harness. The structured JSON output per agent enables automated comparison of engine agreement/disagreement on function health. This should become a standard CI gate.

## Directive

**Before writing another line of harness code, implement a single `EngineAdapter` base class in `src/harness/engines/transport.py` that owns the SSE parse loop, chunk reassembly, `EngineResponse` construction, and `usage` extraction.** Each concrete engine then subclasses it and overrides only `build_payload()` and `endpoint_url()`. Retrofit Kimi, DeepSeek, and MiMo to use it. Add one integration test per engine that dispatches a trivial packet against the real API and asserts `response.tokens_in > 0`. This single refactor eliminates the class of bug that caused W5-V, proves W4-K actually works, and gives you a scaling path to 10+ engines without `concrete.py` becoming unmaintainable. Estimated: 1 session. If it isn't done, the orchestrator toggle work the operator wants will be built on sand.

## Confidence Level

**0.45** — The session shipped real functionality (bilateral no-op guards, engine fallback, orchestrator scaffolding), but the foundation is cracked: token telemetry is inert, engine adapters are bespoke and bug-prone, and the operator has been working around hook noise for half the session. Three months from now, with 6+ engines and nightly runs, every uncaught silent-substitution or zero-token ledger row will compound. The session optimized for feature count over structural integrity.