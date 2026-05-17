# Packet: Wave 2B.4 — Engine-specific guards (packet-trap + bundle splitter + anchor-fuzzy)

## Mission
Produce `src/harness/engines/guards.py` — detection + enrichment layer that wraps engine output to surface engine-specific failure modes BEFORE the broad `except Exception` in `concrete.dispatch` buries them as "internal" (per `ACCEPTED_LIMITATIONS.md` ACCEPT-3, this is where forensic signal is recovered).

## Required API

```python
def classify_response(
    *,
    backend: str,
    model: str | None,
    packet_content: str,
    response: EngineResponse,
) -> EngineResponse: ...

def should_split_kimi_bundle(packet_content: str) -> bool: ...
def split_multi_domain_packet(packet_content: str) -> list[str]: ...
def anchor_fuzzy_check(response_text: str, anchors: list[str]) -> AnchorReport: ...

@dataclass(frozen=True)
class AnchorReport:
    total: int
    byte_exact: int
    fuzzy_match: int
    missing: int
    risk: Literal["LOW", "MED", "HIGH"]
```

## Detection rules

### `classify_response`
Returns the input response with possibly UPDATED `error` field reflecting a more-specific outcome label. Never raises. Used by `dispatcher.dispatch_packet` AFTER a raw engine response is received:

1. **DeepSeek v4-flash packet trap** (per `feedback_deepseek_v4_no_tools_packet.md` memory + v1.2 HIGH-7):
   - Trigger: `backend == "deepseek"` AND `model and model.endswith("-flash")`
   - If `response.text` starts with `{` AND contains `"name":` AND contains `"arguments":` → it's a tool-call attempt instead of patch text. Override outcome:
     - `EngineResponse(success=False, text=response.text, latency_ms=response.latency_ms, error="packet_trap")`
   - The dispatcher then logs `outcome="packet_trap"` to jsonl AND falls back to a different engine.

2. **Kimi empty response / timeout pattern** (per `feedback_engine_anchor_accuracy.md`):
   - Trigger: `backend == "kimi"` AND (response.text strip is empty OR response.text matches `^\s*<\?xml`)
   - Override: `error="kimi_empty_or_xml"` for forensic signal.

3. **Anthropic refusal pattern**:
   - Trigger: `backend == "anthropic"` AND response.text matches `(?i)i (cannot|can't|won't|am unable)` in first 500 chars
   - Override: `error="anthropic_refusal"`

4. **Otherwise**: return response unchanged.

### `should_split_kimi_bundle(packet_content)`
Returns True if packet content has ≥2 distinct `## ` headers AND total length > 8 KB. This is heuristic; Kimi tends to fail (empty response / timeout) on multi-domain bundles per memory.

### `split_multi_domain_packet(packet_content)`
If `should_split_kimi_bundle` is True, split on the second-level `## ` headers. Each sub-packet inherits the document preamble (everything before the first `## ` header). Returns list of full sub-packet strings ready for dispatch.

For Wave 2B, this is a HELPER — the dispatcher does NOT auto-call it. v0.3.x will add `--split-kimi-bundles` flag to harness dispatch.

### `anchor_fuzzy_check(response_text, anchors)`
For each `anchor` in `anchors`:
- Byte-exact match: `anchor in response_text` → count as `byte_exact`
- Fuzzy match: normalize quotes (smart→straight), collapse whitespace, then check → count as `fuzzy_match`
- Neither → count as `missing`
Risk: 
- `HIGH` if missing > 0
- `MED` if fuzzy_match > 0 AND missing == 0
- `LOW` if byte_exact == len(anchors)

Used by Wave 2B.4+ (FIND/REPLACE patch validation). Wave 2C will integrate this into the dashboard "decision archaeology" panel.

## CRITICAL security requirements
1. NEVER log `response.text`, `packet_content`, or `anchors` to console / file / exception — these may contain secrets that the engine echoed back.
2. `classify_response` is a PURE function: no IO, no global state, no logging. It only inspects + returns.
3. All regex patterns module-level compiled.
4. No `eval`/`exec`/`subprocess`/network.

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/engines/guards.py`. Target 200-300 lines. Type-hint everything. Imports: stdlib (`re`, `dataclasses`, `typing`) + `from harness.engines.base import EngineResponse`.

Include module docstring explaining contract + the 4 detection rules + which v1.2 amendments and operator memory entries they implement.

## Reference
- v1.2 amendment HIGH-7 (yaml safety) — orthogonal but reinforces packet-trap detection rationale
- Memory notes from operator's MEMORY.md:
  - `feedback_deepseek_v4_no_tools_packet.md` — DeepSeek v4-flash packet trap
  - `feedback_engine_anchor_accuracy.md` — Kimi multi-domain bundle failures + anchor normalization
- `src/harness/engines/base.py` (EngineResponse — must use, never extend)
- `spec/ACCEPTED_LIMITATIONS.md` ACCEPT-3 (this module IS the forensic-signal layer ACCEPT-3 promised)
