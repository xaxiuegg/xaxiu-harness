# Packet: Wave 2A / SQLite history database layer

## Mission
Produce `src/harness/state/db.py` — SQLite history layer for the 4 tables defined in v1 §4 (dispatches, fallbacks, observer_cycles, status_writes) PLUS the new `routing_changes` audit table added by v1.2 amendment MED-9. ALL queries MUST use parameterised placeholders per v1.2 HIGH-11.

## Required tables (DDL)

Reproduce these schemas exactly. ALL CREATE TABLE statements MUST include `IF NOT EXISTS`.

```sql
CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,           -- UUID
    project TEXT NOT NULL,
    packet_path TEXT,
    backend TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,           -- success, timeout, api_error, packet_trap, fallback, all_fallbacks_exhausted
    outcome TEXT,
    latency_ms INTEGER,
    fallback_to TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fallbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT REFERENCES dispatches(id),
    from_backend TEXT,
    to_backend TEXT,
    reason TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS observer_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    checked_at TEXT DEFAULT (datetime('now')),
    flags TEXT,                     -- JSON array string
    status_count INTEGER
);

CREATE TABLE IF NOT EXISTS status_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    backend_type TEXT,
    written_at TEXT DEFAULT (datetime('now')),
    summary TEXT
);

-- New per v1.2 MED-9 amendment
CREATE TABLE IF NOT EXISTS routing_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now')),
    source TEXT NOT NULL,           -- "ws", "cli", "adapter"
    action TEXT NOT NULL,           -- "priority_change", "burst_start", "lock", "release"
    engine TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    client_ip TEXT                  -- nullable; populated for ws source
);
```

## Required API

```python
def init_db(db_path: str | None = None) -> None: ...
def get_connection() -> sqlite3.Connection: ...  # context manager preferred

def insert_dispatch(project: str, packet_path: str, backend: str, model: str | None) -> str: ...
def update_dispatch_status(dispatch_id: str, status: str, latency_ms: int | None, fallback_to: str | None) -> None: ...
def insert_fallback(dispatch_id: str, from_backend: str, to_backend: str, reason: str) -> None: ...
def insert_observer_cycle(project: str, flags: list[str], status_count: int) -> None: ...
def insert_status_write(project: str, backend_type: str, summary: str) -> None: ...
def insert_routing_change(source: str, action: str, engine: str, old_value: str | None, new_value: str | None, client_ip: str | None) -> None: ...

def query_active_dispatches(project: str | None = None, limit: int = 50) -> list[dict]: ...
def query_recent_events(limit: int = 50) -> list[dict]: ...  # union of latest dispatches + observer + routing
def query_fallback_chain(dispatch_id: str) -> list[dict]: ...
def query_routing_history(engine: str | None = None, limit: int = 50) -> list[dict]: ...
```

## CRITICAL security requirements (v1.2 HIGH-11 amendment §4.1 DB Access Policy)

1. **ALL queries use parameterised placeholders** — `cursor.execute(SQL, (param1, param2, ...))`. f-strings, %-formatting, and `+` concatenation in SQL statements are STRICTLY forbidden. CI grep guard: `! grep -rnE 'execute\(["'"'"']\s*[A-Z]+.*\+' src/`.
2. **Integer `limit` parameters** coerced via `int(value)` AND clamped to max `LIMIT_MAX` (1000, imported from `_constants`).
3. **`project` and other operator-controlled text fields** validated against regex `^[a-z0-9-]{1,32}$` (`PROJECT_NAME_REGEX` from `_constants`) BEFORE persistence. Reject with `ValueError` otherwise.
4. **`source` field on routing_changes**: must be one of `"ws"`, `"cli"`, `"adapter"`. Reject otherwise.
5. **`action` field**: must be one of `"priority_change"`, `"burst_start"`, `"lock"`, `"release"`. Reject otherwise.
6. **NO `executescript()`** with any user-controlled input.
7. **NO views, triggers, or stored procedures** in v0.1.0.

## Implementation
- DB file path: `<repo_root>/state/history.db` (use `DB_FILE_NAME` from `_constants`).
- Connection: `sqlite3.connect(path, check_same_thread=False)` with `row_factory = sqlite3.Row` so query results are dict-like.
- On every connection open, set pragmas:
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA journal_mode = WAL;`
  - `PRAGMA synchronous = NORMAL;`
- Use context manager (`with get_connection() as conn:`) for transactions.
- All inserts return the new row's primary key (or generated UUID for dispatches).
- UUIDs generated via `uuid.uuid4().hex` (no hyphens, 32 chars).
- All query functions return `list[dict]` (convert sqlite3.Row → dict before returning).

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/state/db.py`. Target 250-400 lines. Type-hint everything. Imports: stdlib (`sqlite3`, `uuid`, `contextlib`, `pathlib`, `re`, `typing`) + `from harness._constants import DB_FILE_NAME, LIMIT_MAX, PROJECT_NAME_REGEX`.

Include module docstring explaining contract + parameterised-query mandate.

## Reference
- v1 §4 SQLite schema (lines 200-238) at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1.2 amendments HIGH-11 (§4.1 DB Access Policy) and MED-9 (routing_changes table) at `D:/Projects/xaxiu-harness/spec/v1.2-security-amendments.md`
- `src/harness/_constants.py`
