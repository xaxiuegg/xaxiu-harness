# Architectural Correctness Evaluation: Pattern B

## 1. Summary stance
Pattern B successfully delivers TOS-compliant subprocess dispatch through legitimate Claude Code binaries but contains a critical environment-variable inheritance flaw that will cause silent dispatches to wrong endpoints when the parent shell already contains `ANTHROPIC_*` variables—a common scenario for operators who use Claude Code interactively.

## 2. Concrete concerns (ranked by severity)

### 1. Environment variable inheritance contaminates subprocess context
**Where**: `_build_command` method and subprocess invocation in `ClaudeCodeSubprocessEngine`—while code sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, etc., it doesn't explicitly **clear** the environment before setting these variables.
**Why**: If the parent shell (harness process) already has `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN` set from interactive Claude Code usage, the subprocess inherits these. The explicit `os.environ` modifications in `_build_command` only **override** if they exist, but if the harness process itself has these set, they'll leak through. This causes dispatches to hit wrong endpoints (e.g., Anthropic instead of MiMo) or use wrong credentials.
**Failure rate**: Occasional—manifests whenever operator's shell has Claude Code environment pre-configured (common for developers who use Claude Code interactively).

### 2. Missing `ANTHROPIC_DEFAULT_*_MODEL` aliases cause routing failures
**Where**: Code sets `ANTHROPIC_MODEL` but **not** `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, or `ANTHROPIC_DEFAULT_HAIKU_MODEL`.
**Why**: As documented in MiMo's integration guide, Claude Code internally references "sonnet", "opus", "haiku" models. Without these aliases, internal routing attempts will fail or fall back to Anthropic's models. This breaks Claude Code's internal fallback logic.
**Failure rate**: Common—any dispatch that triggers internal model references.

### 3. `--bare` flag absence causes state leakage
**Where**: `_build_command` method constructs command with `--bare`, but no validation that `--bare` is actually supported by the installed Claude Code version.
**Why**: If `--bare` is missing or misimplemented in a particular Claude Code version, the subprocess inherits session state, hooks, plugins, keychain reads, and CLAUDE.md auto-discovery. This causes non-deterministic behavior and potential credential leakage.
**Failure rate**: Rare—only when Claude Code version changes `--bare` behavior.

### 4. Race condition in concurrent dispatch environment setup
**Where**: Multiple concurrent `ClaudeCodeSubprocessEngine.dispatch()` calls modify `os.environ` simultaneously.
**Why**: `os.environ` is process-global. If two concurrent dispatches set different `ANTHROPIC_BASE_URL` values, they'll interfere with each other. The current implementation doesn't use subprocess-specific environment isolation.
**Failure rate**: Occasional—only under concurrent dispatch loads.

### 5. Subprocess timeout doesn't account for CLI initialization overhead
**Where**: `_DEFAULT_TIMEOUT_S = 300` and `timeout_s` parameter.
**Why**: Claude Code CLI initialization (loading plugins, checking licenses) can take 10-30 seconds independently of the actual inference. The timeout starts at process spawn, not after CLI initialization. This causes premature timeouts for legitimate long-running inferences.
**Failure rate**: Occasional—depends on Claude Code version and system load.

## 3. Concrete strengths

### 1. Correct identity propagation
The design genuinely uses Claude Code's legitimate binary (`claude/2.1.150` in smoke test), satisfying TOS requirements. The `--bare` flag prevents session state contamination while maintaining binary authenticity.

### 2. Provider-reported cost capture
The JSON output parsing (`total_cost_usd`, `usage`) provides accurate cost tracking rather than estimates—a significant improvement over direct-httpx for budget management.

### 3. Graceful model fallback handling
`DEFAULT_MODEL_PER_ENGINE` dictionary provides sensible defaults when callers pass empty models, preventing null-pointer-style failures.

### 4. Clear separation of concerns
The `PROVIDER_ANTHROPIC_ENDPOINTS` dictionary cleanly maps provider names to endpoints, making the routing logic explicit and maintainable.

## 4. Edge cases the design doesn't yet address

### 1. Anthropic CLI interface changes
**Condition**: Anthropic changes `--bare`, `--print`, or `--output-format json` flags in future CLI versions.
**Breakage**: All subprocess dispatches fail silently or produce unparseable output. No version pinning or compatibility checks exist.

### 2. Provider-side client certificate requirements
**Condition**: Providers start requiring client TLS certificates (beyond API keys) for Anthropic-compatible endpoints.
**Breakage**: Subprocess dispatches fail with TLS handshake errors. The design assumes simple API-key authentication.

### 3. Claude Code license enforcement changes
**Condition**: Anthropic adds device fingerprinting or concurrent-session limits to Claude Code licensing.
**Breakage**: Subprocess dispatches fail with licensing errors even with valid subscriptions.

### 4. DeepSeek multimodal content expansion
**Condition**: DeepSeek adds support for image/document content blocks in their Anthropic-compat layer.
**Breakage**: The harness's "text-only" assumption becomes unnecessarily restrictive, preventing valid multimodal dispatches.

## 5. Comparison to alternatives

### (a) Direct-httpx with truthful UA (current pattern)
**Advantage**: No subprocess overhead (2-5s savings per dispatch).
**Disadvantage**: Blocked by provider allowlists—requests fail at the gate. This is the pattern that caused Kimi account termination.

### (b) Operator manually running Claude Code
**Advantage**: No harness complexity, direct access to full Claude Code features.
**Disadvantage**: Loses harness orchestration capabilities (concurrent dispatch, budget tracking, multi-engine panels). Not scalable for automated workflows.

### (c) Proposed alternative: Anthropic SDK with transport layer override
**Advantage**: No subprocess overhead, in-process HTTP calls with correct User-Agent.
**Disadvantage**: Violates TOS (still spoofing identity at code level). The subprocess approach is the **only** TOS-compliant method because it uses the actual binary.

## 6. One concrete change you'd recommend
**File**: `src/harness/engines/claude_code_subprocess.py`
**Function**: `_build_command` and the subprocess invocation logic
**Change**: Implement environment isolation by:
1. Creating a clean environment dictionary: `env = os.environ.copy()`
2. Explicitly deleting conflicting variables: `for key in ['ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL']: env.pop(key, None)`
3. Setting only the required variables: `env.update({...})`
4. Passing this isolated environment to `subprocess.Popen(env=env)`

This prevents parent environment contamination and ensures deterministic dispatch.

## 7. Confidence in your evaluation (0.8)
The environment inheritance flaw is architecturally fundamental and will cause real failures in production environments. Confidence would reach 0.95 with observed failure logs from environments where `ANTHROPIC_*` variables are pre-set.

## 8. What your lens systematically misses
This evaluation focuses on technical correctness but doesn't assess the operational burden of maintaining subprocess compatibility across Claude Code versions, provider endpoint changes, and authentication mechanism evolution—a maintenance cost that could outweigh the architectural benefits over 6-12 months.