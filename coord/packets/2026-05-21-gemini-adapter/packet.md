# Packet: GEMINI-ADAPTER — Gemini 2.x engine adapter for triangulation

## Mission

Add a Google Gemini 2.x engine adapter to `harness.engines` so cross-engine ship-audits can triangulate beyond Kimi ↔ DeepSeek ↔ Anthropic. Gemini's 2M-token window makes it especially valuable for V-file work and full-codebase audit prompts.

Creativity-tick idea (score 71). Promoted under the dev-manager backlog-clear directive.

## In-scope NEW files

- `src/harness/engines/gemini.py` — `GeminiEngine` concrete impl mirroring `harness.engines.concrete` pattern (httpx client, request/response, error mapping)
- `tests/test_engines_gemini.py` — boundary tests (httpx mocked) for happy path + timeout + rate limit + refusal-pattern + packet-trap

## In-scope MODIFY files

- `src/harness/_constants.py` — extend `SUPPORTED_BACKENDS` with "gemini"
- `src/harness/engines/concrete.py::get_engine` — add the `"gemini"` branch returning `GeminiEngine`
- `src/harness/engines/guards.py` — add Gemini-specific refusal patterns if any (otherwise reuse generic)
- Update existing `tests/test_engines_concrete_boundary.py` to confirm `get_engine("gemini")` returns the right class

## API key + endpoint

- `GEMINI_API_KEY` env var (Google AI Studio key)
- Default endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- Default model: `gemini-2.0-flash` (cheap + 1M context); operator can override via `--model gemini-2.5-pro`

DPAPI integration: same pattern as `harness.secrets.dpapi.read_secret("GEMINI_API_KEY")`; surface via `harness env --show-set`.

## Implementation sketch

```python
# src/harness/engines/gemini.py
from __future__ import annotations
import os, time
import httpx
from harness.engines.base import EngineResponse
from harness.engines.concrete import _ConcreteEngineBase  # if present, else duplicate the pattern

GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

class GeminiEngine:
    name = "gemini"
    default_model = "gemini-2.0-flash"

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: dict,
    ) -> EngineResponse:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return EngineResponse(success=False, text="", latency_ms=0,
                                  error="missing_api_key")
        effective_model = model or self.default_model
        url = GEMINI_ENDPOINT_TEMPLATE.format(model=effective_model)
        body = {
            "contents": [{"role": "user", "parts": [{"text": packet_content}]}],
            "generationConfig": {
                "temperature": extra_args.get("temperature", 0.2),
                "maxOutputTokens": extra_args.get("max_output_tokens", 8192),
            },
        }
        started = time.time()
        try:
            response = httpx.post(
                url,
                params={"key": api_key},
                json=body,
                timeout=httpx.Timeout(extra_args.get("timeout", 60.0)),
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            return EngineResponse(success=False, text="",
                                  latency_ms=int((time.time() - started) * 1000),
                                  error="timeout")
        except httpx.HTTPStatusError as exc:
            return EngineResponse(success=False, text="",
                                  latency_ms=int((time.time() - started) * 1000),
                                  error=f"http_{exc.response.status_code}")
        elapsed_ms = int((time.time() - started) * 1000)
        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            return EngineResponse(success=False, text="", latency_ms=elapsed_ms,
                                  error="no_candidates")
        text_parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in text_parts)
        return EngineResponse(success=True, text=text,
                              latency_ms=elapsed_ms, error=None)
```

Match the existing concrete engine implementations style (look at `harness.engines.concrete::KimiAPIEngine` or `DeepSeekEngine` for the canonical pattern).

## Routing rules update (optional, not blocking)

In `coord/dev_loop/dispatch-rules.md`, add a row for Gemini:
- Cross-engine ship audit | Gemini-2.5-pro (when both Kimi+DeepSeek already used) | reserved for triangulation only

## Tests required

1. Missing GEMINI_API_KEY → success=False, error="missing_api_key"
2. Happy path (mocked httpx) returns EngineResponse with text + latency_ms.
3. Timeout returns success=False, error="timeout".
4. HTTP 429 returns success=False, error="http_429".
5. Empty candidates returns success=False, error="no_candidates".
6. `get_engine("gemini")` returns a GeminiEngine instance.
7. "gemini" in SUPPORTED_BACKENDS.
8. Existing concrete engine tests still pass.

Target ≥7 new tests.

## Acceptance criteria

1. `harness engines` (which lists supported backends) shows "gemini".
2. `harness env --show-set` recognises `GEMINI_API_KEY`.
3. `python -m pytest tests/ -q` shows ≥488 + new tests, all green.
4. Single commit: `feat(engines): Gemini 2.x adapter for cross-engine triangulation (GEMINI-ADAPTER)`.

## Reference

- `src/harness/engines/concrete.py` — pattern source (KimiAPIEngine, DeepSeekEngine)
- `src/harness/engines/base.py` — EngineResponse contract
- `src/harness/engines/guards.py` — refusal-pattern + packet-trap classifier (Gemini may need its own patterns)
- `src/harness/secrets/dpapi.py` — secrets storage (operator can store GEMINI_API_KEY there)

## Output format

1 new engine file + 1 new test file + 4 modify files + 1 commit.
