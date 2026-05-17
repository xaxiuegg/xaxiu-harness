# Packet: Wave 2B.1 — Engine concrete httpx dispatch

## Mission
Produce `src/harness/engines/concrete.py` — concrete `Engine` implementations for DeepSeek, Kimi, and Anthropic, each performing real httpx-based API dispatch. Replaces the Wave 1 stubs by subclassing `Engine` from `engines/base.py`.

## Required classes
- `DeepSeekConcrete(Engine)` — POSTs to DeepSeek Platform API v1 chat completions endpoint
- `KimiConcrete(Engine)` — POSTs to Kimi (Moonshot) chat completions endpoint
- `AnthropicConcrete(Engine)` — POSTs to Anthropic Messages API

Plus a factory: `get_engine(name: str, *, prefer_dpapi: bool = True) -> Engine`

## Endpoints (use these exact URLs)
- DeepSeek: `https://api.deepseek.com/v1/chat/completions`
- Kimi: `https://api.moonshot.cn/v1/chat/completions`
- Anthropic: `https://api.anthropic.com/v1/messages` (header `anthropic-version: 2023-06-01`)

## Required dispatch behavior
For each engine, `dispatch(packet_content, model, extra_args)` MUST:
1. Build the chat-completions payload: single `user` message with `packet_content` as the text content. `model` is the model name (e.g. `"deepseek-v4-flash"`, `"moonshot-v1-32k"`, `"claude-sonnet-4-6"`).
2. Apply engine-specific guards from extra_args (v1.2 amendments — Wave 2B.4 will add the orchestration layer, but THIS file must respect the flags):
   - DeepSeek: if `extra_args.get("--no-thinking")` is truthy OR `model.endswith("-flash")`, POST with `temperature=0.0` and include `"thinking": False` in the body (per DeepSeek v4-flash packet-trap mitigation)
   - Kimi: respect `extra_args.get("temperature")` (default 0.6)
   - Anthropic: requires `max_tokens` (default 8192)
3. Set timeout: httpx.Timeout(connect=10s, read=120s, write=10s, pool=10s).
4. On HTTP 2xx with non-empty response: return `EngineResponse(success=True, text=extracted_text, latency_ms=int_round, error=None)`
5. On HTTP 4xx/5xx: return `EngineResponse(success=False, text="", latency_ms=int_round, error=f"HTTP {status}")` — do NOT include response body in error (HIGH-9 amendment: closed-schema log writes).
6. On timeout / network error: return `EngineResponse(success=False, text="", latency_ms=elapsed, error="timeout" or "network")`.
7. On any other exception: catch broadly, return `EngineResponse(success=False, text="", latency_ms=elapsed, error="internal")` — NEVER raise; NEVER expose stack trace.

## API key resolution (`get_engine` factory)
1. If `prefer_dpapi=True` and `secrets.dpapi.has_secret(env_var_name)`, use `secrets.dpapi.decrypt_secret(env_var_name)`.
2. Else fall back to `os.environ.get(env_var_name)`.
3. If neither yields a key → raise `RuntimeError(f"No API key for {name}. Run `harness env` to verify.")` (NEVER include attempted values in the error).

Env var names sourced from `harness._constants.API_KEY_ENV_VARS`.

## CRITICAL security requirements
1. **NEVER** include API keys in:
   - HTTP request/response logging
   - Exception messages
   - `__repr__` output (concrete classes inherit base `__repr__` which is already safe)
   - `EngineResponse.error` field
   - `EngineResponse.text` field
2. **NEVER** log packet content (HIGH-9 closed-schema rule — Wave 2B.3 jsonl writer enforces the schema).
3. **NEVER** log response body on error (could contain echoed API key from 401/403 responses).
4. All HTTP calls via httpx (`import httpx`) — NO `requests`, NO `urllib`. Use httpx.Client with `verify=True` (default; explicit for clarity).
5. NO `verify=False` anywhere. Reject any extra_args that contain TLS-disabling flags.
6. Timeout MUST be set on every request (the httpx.Timeout above).
7. `User-Agent` header: `f"xaxiu-harness/{harness.__version__}"` — no system info.

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/engines/concrete.py`. Target 300-500 lines. Type-hint everything. Imports: stdlib (`time`, `typing`, `os`) + `httpx` + `from harness._constants import API_KEY_ENV_VARS` + `from harness.engines.base import Engine, EngineResponse` + `from harness.secrets import dpapi`.

Include module docstring + per-class docstrings explaining the engine + which extra_args are honored.

## Reference
- v1 spec §10 (Engine ABC contract) at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1.2 amendments HIGH-8 (DPAPI integration), HIGH-9 (no leak in logs/errors)
- v1.2 amendment for HIGH-7 (DeepSeek v4-flash packet trap — `--no-thinking` required)
- `src/harness/engines/base.py` (Engine ABC + EngineResponse — must subclass)
- `src/harness/_constants.py` (API_KEY_ENV_VARS, SUPPORTED_BACKENDS)
- `src/harness/secrets/dpapi.py` (has_secret, decrypt_secret)
