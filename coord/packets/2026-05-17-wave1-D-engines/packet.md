# Packet: Wave 1 / D — Engine ABC + concrete stubs

## Mission
Produce `src/harness/engines/base.py` — `Engine` abstract base class + `EngineResponse` dataclass + 3 concrete engine stub classes (`DeepSeekEngine`, `KimiEngine`, `AnthropicEngine`) all implementing the ABC. Dispatch logic itself is Wave 2; this packet sets up the structure and contracts.

## Required classes

### `EngineResponse` (frozen dataclass)
```python
@dataclass(frozen=True)
class EngineResponse:
    success: bool
    text: str
    latency_ms: int
    error: Optional[str] = None
```

### `Engine` (ABC)
```python
class Engine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dispatch(self, packet_content: str, model: str, extra_args: dict) -> EngineResponse: ...
```

### `DeepSeekEngine`, `KimiEngine`, `AnthropicEngine` (concrete stubs)
- Each `__init__(self, api_key: Optional[str] = None)`: if `api_key` is None, read from env var (KIMI_API_KEY / DEEPSEEK_API_KEY / ANTHROPIC_API_KEY respectively). Store as `self._api_key` (private).
- Each `name` property: returns `"deepseek"` / `"kimi"` / `"anthropic"` respectively
- Each `dispatch` method: returns `EngineResponse(success=False, text="", latency_ms=0, error="dispatch not implemented in Wave 1")`
- Each `__repr__`: returns `f"{class_name}(api_key={'SET' if self._api_key else 'MISSING'})"` — NEVER the actual key value
- Each class docstring: notes which engine-specific guards (from v1 spec §7) will apply in Wave 2 (e.g., DeepSeek will get auto `--no-thinking` for patches; Kimi will get bundle splitting)

## CRITICAL security requirements
1. API keys MUST come from env vars by default (`KIMI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`)
2. `__repr__` of every engine class MUST show `"api_key=SET"` or `"api_key=MISSING"` — NEVER the actual value, even truncated
3. `dispatch` stubs MUST NOT include `api_key` in printed/returned output
4. No `__str__` override that exposes key
5. Module-level constant: `SUPPORTED_BACKENDS = ["deepseek", "kimi", "anthropic"]` for routing reference (NOT including "burst" which is multi-engine, handled at router level not engine level)
6. Use `os.environ.get(key)` (returns None if missing) — NEVER `os.environ[key]` (raises KeyError which could leak via traceback)

## Required structure
- Module docstring explaining the ABC contract (operator-friendly: "Engines are pluggable backends. The harness selects one per dispatch per routing rules + priority + fallback chain.")
- Use `dataclasses.dataclass(frozen=True)` for `EngineResponse`
- Use `abc.ABC` and `@abstractmethod` decorators
- Class docstrings explaining each engine's expected behavior (full impl deferred to Wave 2)
- Type hints throughout
- Target 150-250 lines

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/engines/base.py`. Imports only stdlib (abc, dataclasses, os, typing). No third-party imports in Wave 1; engine API calls will land in Wave 2 with httpx.

## Reference
- v1 spec §10 (Plugin Interface — Engine ABC code shown) at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1 spec §7 (Engine-Specific Guards — note which guards apply where, but DON'T implement guards in Wave 1; just docstring-document them)
- v1 spec §4 (engine_health.json shape — engines populate this in Wave 2)
