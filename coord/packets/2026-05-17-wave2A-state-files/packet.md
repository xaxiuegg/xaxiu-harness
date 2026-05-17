# Packet: Wave 2A / State JSON file helpers

## Mission
Produce `src/harness/state/files.py` — Pydantic-typed read/write helpers for the JSON+YAML state files defined in v1 §4: `harness.config.yml`, `state/active_dispatches.json`, `state/loops.json`, `state/engine_health.json`.

## Required Pydantic v2 models

```python
class HarnessConfig(BaseModel):
    harness_version: str
    default_project: str | None = None
    installed: bool = False
    task_scheduler_prefix: str = "xaxiu-harness-"
    model_config = {"extra": "forbid"}

class ActiveDispatch(BaseModel):
    dispatch_id: str              # UUID
    project: str
    packet_path: str
    backend: Literal["deepseek", "kimi", "anthropic"]
    model: str | None = None
    started_at: str               # ISO 8601 UTC
    status: Literal["running", "complete", "failed", "fallback"]
    fallback_count: int = 0
    current_backend: str | None = None
    model_config = {"extra": "forbid"}

class LoopEntry(BaseModel):
    name: str
    command: str                  # must start with "harness "
    cron: str
    enabled: bool = True
    task_name: str                # full Windows Task Scheduler name
    model_config = {"extra": "forbid"}

class EngineHealth(BaseModel):
    status: Literal["up", "degraded", "down"] = "up"
    last_fail: str | None = None  # ISO 8601 UTC
    avg_latency_ms: int | None = None
    priority: Literal["HIGH", "NORMAL", "AVOID"] = "NORMAL"
    burst_until: str | None = None
    locked: bool = False
    model_config = {"extra": "forbid"}
```

## Required functions

```python
def read_harness_config() -> HarnessConfig: ...
def write_harness_config(cfg: HarnessConfig) -> None: ...

def read_active_dispatches() -> list[ActiveDispatch]: ...
def write_active_dispatches(items: list[ActiveDispatch]) -> None: ...
def append_active_dispatch(item: ActiveDispatch) -> None: ...

def read_loops() -> list[LoopEntry]: ...
def write_loops(items: list[LoopEntry]) -> None: ...

def read_engine_health() -> dict[str, EngineHealth]: ...
def write_engine_health(state: dict[str, EngineHealth]) -> None: ...
def update_engine_health(name: str, patch: dict) -> None: ...  # partial update + write
```

## Implementation
- All state files under `<repo_root>/state/`. Resolve via `Path(__file__).resolve().parents[3] / "state"` (or read from a `STATE_DIR` constant injected at runtime — choose one and stick to it).
- `harness.config.yml` uses `yaml.safe_load` for reading, `yaml.safe_dump` for writing. NEVER `yaml.load`.
- JSON files (`*.json`) use `json.load` / `json.dump(..., indent=2)`.
- All writes atomic: `tempfile.NamedTemporaryFile` in same directory → fsync → `os.replace(tmp, target)`.
- All reads handle missing file gracefully: return empty list/dict, NOT raise.
- All reads handle corrupted file with `StateFileCorruptError(path)` exception — NEVER include file contents in the exception message (per v1.2 LOW-3 amendment).
- All writes set file mode 0600 via `os.chmod` after replace.

## CRITICAL security requirements
1. `yaml.safe_load` for harness.config.yml — NEVER `yaml.load`, `yaml.unsafe_load`, or `yaml.FullLoader` (per v1.2 HIGH-7).
2. On parse errors, raise with file path but NEVER content (LOW-3).
3. File mode 0600 after every write (sensitive runtime state).
4. Atomic writes prevent torn reads.
5. NO eval, NO exec, NO subprocess.

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/state/files.py`. Target 250-400 lines (includes all Pydantic models + 10 functions). Type-hint. Imports: stdlib (`json`, `os`, `pathlib`, `tempfile`, `typing`) + `yaml` + `pydantic` + `from harness._constants import ...`.

Define a custom exception class `StateFileCorruptError(Exception)` near the top.

## Reference
- v1 §4 state file shapes (JSON examples shown)
- v1.2 amendments HIGH-7 (yaml.safe_load), LOW-3 (no file contents in errors)
- `src/harness/_constants.py`
