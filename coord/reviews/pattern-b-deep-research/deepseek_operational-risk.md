# Operational Risk Evaluation: Claude Code Subprocess Engine (Pattern B)

## 1. Summary stance

The design’s central bet – using the local Claude Code binary as a proxy for provider authentication – introduces a cluster of failure mechanisms around environment isolation, binary version drift, and resource exhaustion at scale. The highest-probability risk is silent environment‑variable leakage between concurrent dispatches (a common Python subprocess pitfall), while the highest‑impact risk is model‑name drift on the provider side that silently breaks all dispatches for a given provider without operator awareness.

## 2. Concrete concerns (ranked by severity)

### A. Environment‑variable leakage between concurrent dispatches (probability: common) [severity: high]

The code sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, and potentially `ANTHROPIC_DEFAULT_*_MODEL` for each subprocess invocation. If the `dispatch` method modifies `os.environ` globally (or passes an incomplete `env` dict that inherits parent keys), a concurrent subprocess for provider B could see provider A’s API key or base URL. The snippet does **not** show the subprocess call; we see only `_build_command` (line ~99). In the live smoke test the env vars were set inline in the shell, but the harness must isolate them per call. Python’s `subprocess.Popen(env=...)` replaces the entire environment, so if the code uses `os.environ.copy()` and then adds keys, that copy is safe. If instead it mutates `os.environ` (even temporarily) before spawn, another thread’s subprocess inherits the mutated state. Given typical production code patterns, this is a common mistake.

**Why it matters:** A leaked token could cause cross‑provider billing, authentication failure, or accidental exposure of the operator’s credential. At 10‑parallel push, the race condition will fire regularly.

### B. Provider‑side model‑name drift (probability: occasional) [severity: very high]

`DEFAULT_MODEL_PER_ENGINE` (lines 76–84) hardcodes model names like `"mimo-v2.5-pro"` and `"kimi-k2.6"`. Providers rename or deprecate models without notice. If Moonshot changes `kimi-k2.6` to `kimi-k3`, every dispatch to `kimi-via-cc` will fail with “model not found”. Because the subprocess returns non‑zero exit code (unlikely to be silently swallowed if error handling is minimal), but the failure may manifest as an HTTP 404 from the provider wrapped in Claude Code’s JSON error output. The harness does **not** seem to have a model‑name discovery or fallback mechanism (FINDINGS.md explicitly flags this as unanswered in the “What this research does NOT yet answer” section).

**Why it matters:** A single provider rename can take an entire engine offline until the operator manually updates the dictionary. In a panel relying on that engine, the panel either fails or falls back to another engine – possibly silently. Impact on reliability is high.

### C. Binary version drift (probability: occasional) [severity: high]

The command line is built with flags `--bare`, `--print`, `--output-format json`, `--no-session-persistence`, `--permission-mode auto`. Claude Code is a rapidly evolving Node.js CLI. Anthropic may deprecate or rename any of these flags. The smoke test used version 2.1.150; future versions may introduce breaking changes. The code has no version detection or fallback command variant. If a flag is removed, the subprocess returns an error, and all dispatches fail until the harness is patched.

**Why it matters:** This is a single point of failure for the entire Pattern B path. Without a version probe or a tolerant command construction, a minor CLI update to block `--bare` could silently halt production.

### D. Subprocess resource exhaustion at 10+ parallel (probability: common) [severity: high]

Each `claude` subprocess spawns a Node.js runtime loading the full CLI binary. Based on the smoke test (9.6 seconds, 0.01 USD), the process likely consumes 100–200 MB RSS. Ten parallel processes → 1–2 GB RAM, plus CPU time for startup (each Node.js init can take 1–2s). On a typical dev machine or small server, this can cause swap thrashing, OOM kills, or excessive context switching. The design acknowledges this (line 32: “Concurrent dispatch is process-pool-bound, not connection-pool-bound”) but **does not impose any concurrency limit**. The harness could support 10+ panels each dispatching simultaneously – a realistic scenario. The code has no resource pool, no semaphore, and no monitor on total resident memory.

**Why it matters:** Resource exhaustion degrades latency for all concurrent dispatches and can take down the entire harness process.

### E. Binary deletion / missing (probability: rare) [severity: very high]

If the operator deletes the `claude` binary or changes PATH, `_resolve_binary()` (line 89) returns either `os.environ.get("HARNESS_CLAUDE_CODE_BINARY")` or `"claude"`. Neither checks existence. The subprocess will raise `FileNotFoundError` (on Linux) or `WindowsError` (on Git Bash). There is no fallback, no diagnostic, and no graceful degradation. Since Pattern B is the only path for providers that forbid direct access, losing the binary stops all dispatches to those providers.

**Why it matters:** A single accidental deletion or PATH change makes the harness useless for provider‑gated engines. Recovery requires operator intervention with no in‑process alerting.

### F. Interaction with W14-DISPATCH-HEALTH-AWARE-FALLBACK probe loop (probability: occasional) [severity: medium]

The health probe loop (not shown in source pack) likely pings engines with a short timeout (e.g., 5 seconds). The Claude Code subprocess has a startup overhead of 2–5 seconds plus inference time. If the probe timeout is too tight, the subprocess is killed early, the probe marks the engine unhealthy, and the fallback logic activates – even though the engine would have worked given a few more seconds. This is a tuning issue, not a code defect, but the risk is real. The code’s default timeout is 300s (`_DEFAULT_TIMEOUT_S`, line 52), which is huge for a health check. If the probe uses a different timeout, false negatives will occur.

**Why it matters:** False health negatives degrade panel availability by forcing unnecessary fallback, increasing latency and cost.

### G. Audit‑trail incompleteness for subprocess failures (probability: common) [severity: low]

The subprocess is expected to output JSON. If the subprocess crashes (non‑zero exit, stderr output), the `dispatch` method must capture stderr and log it. The code snippet does not show error handling. Without proper logging, silent failures will produce gaps in the audit trail – no session_id, no cost, no error reason. Operators might see “dispatch failed” without knowing why (e.g., model not found, binary crash, provider timeout).

## 3. Concrete strengths

- **Legitimate User‑Agent**: The core design goal is met. The subprocess sends `claude/<version>` (observed as `claude/2.1.150` in the smoke test). This satisfies provider allowlists and TOS, as confirmed by the successful smoke test. The distinction from the banned OpenClaw pattern is correctly argued.

- **Provider‑reported cost capture**: The JSON output includes `total_cost_usd` and detailed `modelUsage`. This is more accurate than token‑based estimation used in direct‑httpx. The cost is flowing into the response (EngineResponse presumably has `cost_usd`). Good for budget tracking.

- **Clean isolation via `--bare`**: The `--bare` flag correctly strips session state, hooks, and `CLAUDE.md`. Each dispatch is a fresh sandbox, reducing cross‑contamination from previous runs.

- **Extensible provider registry**: `PROVIDER_ANTHROPIC_ENDPOINTS` and `DEFAULT_MODEL_PER_ENGINE` are dictionaries keyed by canonical names. Adding a new provider is a one‑line addition. The region‑aware MiMo resolution (`_resolve_mimo_tp_region`) is well‑done.

- **Sensible error handling in `_build_command`**: The method constructs the command with clear defaults and overrides via `extra_args`. The permission mode and budget are parameterized, not hardcoded.

## 4. Edge cases the design doesn't yet address

- **Provider model name changes without deprecation period**: If a provider silently deprecates a model and returns a generic error (e.g., HTTP 500), the subprocess will fail without a clear signal. No fallback to an alternative model for that provider.

- **Network proxy or corporate firewall**: The subprocess inherits the parent process’s environment, but `ANTHROPIC_BASE_URL` may need to be overridden for a proxy. If the operator uses `http_proxy` env vars, they will be inherited, but if not, the subprocess may fail to reach the provider. The design does not expose a proxy configuration.

- **Claude Code binary installed via different path (e.g., `npx`, snap, homebrew)**: `_resolve_binary` only checks `HARNESS_CLAUDE_CODE_BINARY` and bare `"claude"`. If the operator uses `npx @anthropic-ai/claude-code`, the command must be different. The design does not accommodate `npx` invocation.

- **Concurrent dispatches to the same provider with different API keys**: Not directly supported because the provider key is set via env var at subprocess level. If the same provider engine is instantiated with two different keys (e.g., two accounts), each subprocess correctly gets its own key, but the provider may rate‑limit based on key – valid.

- **Windows NT / non‑POSIX environment**: The `subprocess.Popen` call likely uses `shell=False` with a list command, which is fine on Windows. But the binary path resolution and `claude` name may not work on Windows without additional configuration. The comment at line 48 mentions Windows (Git Bash), but there is no fallback.

- **Subprocess hanging indefinitely**: If the provider’s API hangs, the subprocess will not exit and `subprocess.run(timeout=...)` will raise `TimeoutExpired`. The code uses `timeout_s` parameter – good. But if the timeout is too generous (300s default) and many subprocesses hang, resource exhaustion worsens. No kill‑after‑timeout cleanup (like `process.kill()` after exception) is shown.

## 5. Comparison to alternatives

**(a) Direct‑httpx with truthful UA (today's pattern)**: Fails at provider gates (for allowlisted providers). Not viable where UA is checked. The subprocess pattern is necessary for those providers. However, direct‑httpx is lighter (no subprocess overhead), supports connection pooling, and is easier to instrument. If the provider gate can be bypassed (e.g., using a proxy that re‑writes UA), direct‑httpx would be simpler. But that introduces its own legal risk.

**(b) Operator manually running Claude Code interactively**: No automation, no harness integration. Operator must manually dispatch each panel conversation, record results, and feed back. Not scalable to multi‑engine panels. The harness provides orchestration, retries, and cost tracking. Automated subprocess is strictly better for panel workflows.

**(c) A pattern not yet proposed: run a persistent Claude Code daemon (e.g., via `claude --daemon` or websocket)**: The subprocess startup overhead (2–5s per dispatch) could be eliminated by keeping a long‑lived Claude Code process that accepts dispatches via stdin/stdout or a socket. This would reduce latency and resource cost (no repeated Node.js init). However, it introduces statefulness – daemon health, session management, and potential memory leaks. The current subprocess pattern trades startup cost for simplicity and isolation. A daemon pattern would be a strong future optimization but adds operational complexity.

Given these, the subprocess pattern is a reasonable middle ground. Its main weakness is overhead at scale, which could be mitigated by a process pool with a fixed maximum concurrency.

## 6. One concrete change you'd recommend

**Implemented before ship:** In the `dispatch` method (not shown but assumed to be the subprocess runner), enforce a **strict per‑dispatch environment isolation** using `subprocess.Popen(env=...)` with a **fresh dictionary that contains only the required keys** – no inheritance from `os.environ` except for standard variables like `PATH` and `HOME`. Additionally, **add a `concurrency_semaphore` (e.g., `threading.Semaphore` with default max 4) to cap parallel subprocesses** to prevent resource exhaustion. The semaphore should be configurable via a constructor argument or global setting. This directly addresses the highest‑probability risk (env leakage) and the highest‑impact risk (resource exhaustion).

Specifically:  
- Replace `subprocess.run(cmd, env=os.environ)` (if that is what is used) with `subprocess.run(cmd, env={**required_vars, "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "SHELL": os.environ.get("SHELL", "")})`.  
- Add `from threading import Semaphore` and `self._semaphore = Semaphore(kwargs.get("max_concurrency", 4))` in `__init__`. Wrap the subprocess call in `with self._semaphore:`.

This mitigation is low‑effort, high‑impact, and directly addresses the two top concerns.

## 7. Confidence in your evaluation (0.0–1.0)

**0.85** – Confidence is high because the source material explicitly shows the env‑var setup pattern and the absence of concurrency controls. The largest uncertainty is the complete `dispatch` method (not shown), which could already handle env isolation correctly. If the code already uses `subprocess.run(..., env=sanitized_env, ...)`, the env‑leakage risk drops to “rare”. My assessment assumes the unsafe pattern based on common implementation errors; if the actual code is safe, reevaluate to ~0.8.

## 8. What your lens systematically misses

This evaluation underweights **operator ergonomics** – how easy it is for a human to diagnose and recover from failures. I focused on technical failure modes but did not examine the DX of inspecting a crashed subprocess, parsing its JSON error output, or understanding why a provider returned a “model not found” error versus a transient network blip. Operational risk includes mean time to recovery, not just mean time to failure.