# xaxiu-harness v1 Architecture Specification

## 1. Repo Layout

```
D:/xaxiu-harness-standalone/
├── src/harness/               # Core Python package (CLI, engine abstraction, scheduler)
│   ├── cli.py                 # Click-based CLI verbs
│   ├── engines/               # Built-in backends (DeepSeek, Kimi, Anthropic)
│   │   ├── __init__.py
│   │   ├── base.py            # ABC Engine
│   │   ├── deepseek.py
│   │   ├── kimi.py
│   │   └── anthropic.py
│   ├── adapters/              # Adapter loader (reads YAML from adapters/ dir)
│   │   ├── loader.py
│   │   ├── schema.py          # Pydantic schema for adapter YAML
│   │   └── warehouse_example.yaml (doc only)
│   ├── state/                 # State file management (JSON + SQLite)
│   ├── dashboard/             # FastAPI app + WebSocket endpoint
│   ├── installer/             # Windows Task Scheduler installer
│   └── utils.py
├── adapters/                  # Per-project YAML files (operator-edited)
│   ├── warehouse/             # Example: xaxiu-harness-warehouse adapter
│   │   ├── harness-adapter.yaml
│   │   └── scheduled_tasks/
│   └── generic-project/
├── spec/                      # This document and any subsequent contracts
│   └── v1-architecture.md
├── coord/                     # Operator’s dispatch packets
├── tests/                     # Pytest suite
├── installer/                 # Windows installer bundle (Inno Setup script, embedded Python)
│   └── first-run-wizard.ps1
├── dashboard/                 # Static assets (HTML/CSS/JS) for frontend
│   └── index.html
└── README.md
```

## 2. Adapter YAML Schema

**Schema definition (Pydantic model equivalent):**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Project name (used for task naming) |
| `project_root` | string | yes | Absolute path to project directory |
| `routing_rules` | array | no | Ordered list of if/then/reason rules |
| `status_tracking` | object | yes | Backend config (csv, markdown, jira, linear) |
| `observer` | object | yes | Observer cycle settings |
| `scheduled_tasks` | array | no | Additional `schtasks` entries for this project |

**`routing_rules[].`**:

| Field | Type | Description |
|---|---|---|
| `if` | string | Condition (glob or regex on packet file path / content) |
| `then` | object | `backend`, `model`, optional `extra_args` |
| `reason` | string | Human-readable justification |

**`status_tracking`**:

| Field | Type | Descriptive |
|---|---|---|
| `backend` | string | One of `csv`, `markdown`, `jira`, `linear` |
| `config` | object | Backend-specific (e.g., `csv_path`, `jira_project_key`) |

**`observer`**:

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | true | Enable observer cycles |
| `cadence_minutes` | int | 30 | How often `observer-tick` runs |
| `daily_retro_time` | string | `"17:00"` | Time for retro task |
| `flag_patterns` | array | `[".*FAIL.*", ".*BLOCKER.*"]` | Patterns to flag in status logs |

**`scheduled_tasks[].`**:

| Field | Type | Required | Description |
|---|---|---|---|
| `cron` | string | yes | Windows schtasks format (e.g., `"0 9 * * 1-5"`) |
| `command` | string | yes | `harness <verb> <args>` |
| `idempotent` | bool | yes | True if task can be run multiple times safely |

**Complete warehouse adapter example** (`D:/xaxiu-harness-standalone/adapters/warehouse/harness-adapter.yaml`):

```yaml
name: warehouse
project_root: D:/Projects/warehouse
status_tracking:
  backend: csv
  config:
    csv_path: STATUS.csv
    headers: [date, task, engine, status, notes]
routing_rules:
  - if: "packet*.md"  # all packets in project root
    then:
      backend: deepseek
      model: deepseek-v4-flash
      extra_args: { "--no-thinking": true }
    reason: "Default for warehouse – patches need anchor precision"
  - if: "*-screenshots-*"
    then:
      backend: kimi
      model: kimi-v2
    reason: "Only Kimi handles screenshot extraction"
observer:
  enabled: true
  cadence_minutes: 30
  daily_retro_time: "17:00"
  flag_patterns:
    - ".*FAIL.*"
    - ".*BLOCKER.*"
scheduled_tasks:
  - cron: "0 9 * * 1-5"
    command: "harness observer-tick --project warehouse"
    idempotent: true
  - cron: "0 17 * * 1-5"
    command: "harness retro --project warehouse"
    idempotent: false
  - cron: "0/15 * * * *"
    command: "harness status --project warehouse --report"
    idempotent: true
```

## 3. CLI Command Surface

All verbs invoked via `harness <verb>`. Exit codes: 0 = success, 1 = generic error, 2 = engine failure (with fallback), 3 = lock conflict.

| Verb | Signature | Description |
|---|---|---|
| `dispatch` | `[--project P] [--packet FILE] [--backend B] [--model M] [--force-engine ENGINE]` | Execute a packet; if no backend given, auto-route per adapter rules. |
| `status` | `[--project P] [--report] [--format (csv|json)]` | Print current status (or report to configured backend). |
| `observer-tick` | `[--project P]` | Run one observer cycle: check status changes, flag patterns. |
| `retro` | `[--project P] [--date YYYY-MM-DD]` | Generate daily retro summary from history. |
| `install` | (no args) | Setup Task Scheduler entries and first-run wizard. |
| `init` | `[--project P] [--template warehouse\|basic]` | Create starter adapter YAML. |
| `env` | `[--show-set]` | Check which API keys are set (echo `SET` only). |
| `dashboard-serve` | `[--port 8080]` | Start FastAPI dashboard server. |
| `loops` | `[--project P] [--add "name::command::cron"] [--remove name]` | Manage user-defined scheduled loops. |
| `engines` | `[--list] [--health] [--priority ENGINE PRIORITY] [--burst ENGINE DURATION] [--lock ENGINE [--release]]` | Query/modify engine pool. |
| `priority` | `[ENGINE HIGH\|NORMAL\|AVOID]` | Set persistent routing priority per engine. |
| `burst` | `[ENGINE DURATION(min)]` | Temporarily route all traffic to one engine. |
| `lock` | `[ENGINE [--release]]` | Exclusive routing lock (disables auto-routing). |

## 4. State File Format

### Global config: `D:/xaxiu-harness-standalone/state/harness.config.yml`

```yaml
harness_version: "1.0"
default_project: warehouse
installed: true  # set by `harness install`
task_scheduler_prefix: "xaxiu-harness-"
```

### Active dispatches: `state/active_dispatches.json`

```json
[
  {
    "dispatch_id": "uuid",
    "project": "warehouse",
    "packet_path": "packet-2026-05-17.md",
    "backend": "deepseek",
    "model": "deepseek-v4-flash",
    "started_at": "2026-05-17T14:30:00Z",
    "status": "running",
    "fallback_count": 1,
    "current_backend": "kimi"
  }
]
```

### Loops: `state/loops.json`

```json
[
  {
    "name": "warehouse-observer",
    "command": "harness observer-tick --project warehouse",
    "cron": "*/30 * * * *",
    "enabled": true,
    "task_name": "xaxiu-harness-warehouse-observer"
  }
]
```

### Engine health: `state/engine_health.json`

```json
{
  "deepseek": { "status": "up", "last_fail": null, "avg_latency_ms": 4500 },
  "kimi": { "status": "degraded", "last_fail": "2026-05-17T12:00:00Z", "avg_latency_ms": 8200 },
  "anthropic": { "status": "down", "last_fail": "2026-05-17T10:00:00Z", "avg_latency_ms": null }
}
```

### SQLite schema for `state/history.db`

```sql
CREATE TABLE dispatches (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    packet_path TEXT,
    backend TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,       -- success, timeout, api_error, packet_trap, fallback
    outcome TEXT,
    latency_ms INTEGER,
    fallback_to TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE fallbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispatch_id TEXT REFERENCES dispatches(id),
    from_backend TEXT,
    to_backend TEXT,
    reason TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE observer_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    checked_at TEXT DEFAULT (datetime('now')),
    flags TEXT,   -- JSON array of flagged issues
    status_count INTEGER
);

CREATE TABLE status_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    backend_type TEXT,
    written_at TEXT DEFAULT (datetime('now')),
    summary TEXT
);
```

## 5. Dashboard Data Contracts

### REST endpoints (FastAPI)

- `GET /api/engine-pool` → engine health + priorities
- `GET /api/active-dispatches` → list of running/failed dispatches
- `GET /api/loops` → scheduled loops with next run
- `GET /api/events?limit=50` → recent events (dispatch, fallback, observer flags)

### JSON shapes

**Engine pool response:**
```json
{
  "engines": [
    { "name": "deepseek", "health": "up", "priority": "HIGH", "latency_ms": 4500, "burst_remaining_min": 0, "locked": false }
  ]
}
```

**Active dispatches response:**
```json
{
  "dispatches": [
    {
      "id": "abc123",
      "project": "warehouse",
      "packet": "packet.md",
      "engine": "kimi",
      "status": "running",
      "started_at": "2026-05-17T14:30:00Z",
      "fallback_chain": ["deepseek", "kimi"]
    }
  ]
}
```

**Events response:**
```json
{
  "events": [
    { "type": "dispatch_complete", "data": { "dispatch_id": "x", "result": "success" }, "timestamp": "..." }
  ]
}
```

### WebSocket endpoint: `ws://localhost:8080/ws`

Message types (JSON):

| Type | Direction | Data fields |
|---|---|---|
| `engine_status` | server→client | `engine`, `status`, `latency_ms` |
| `dispatch_update` | server→client | `dispatch_id`, `status`, `fallback_to` |
| `observer_flag` | server→client | `project`, `flag`, `timestamp` |
| `priority_change` | client→server | `engine`, `new_priority` |
| `burst_start` | client→server | `engine`, `duration_min` |
| `lock` | client→server | `engine`, `action` (set/release) |

## 6. Task Scheduler Installer Flow

`harness install` does:

1. **Schedule core tasks** (idempotent):
   - `xaxiu-harness-global-status` — runs every 15 min: `harness status --all-projects --report`
   - `xaxiu-harness-engine-health-check` — runs every 5 min: `harness engines --health --auto-fallback`
   - `xaxiu-harness-dashboard` — runs at system startup: `harness dashboard-serve`
   - `xaxiu-harness-first-run-wizard` — runs once after install only

2. **Schedule per-project tasks** from each adapter’s `scheduled_tasks` list.

**Naming convention**: `xaxiu-harness-<project>-<custom_task_name>`

**Idempotency**: All `schtasks /create` with `/F` (force overwrite). No duplicate tasks; if task exists, it is updated. Running `install` twice is safe.

**Uninstall**: `harness install --uninstall` runs `schtasks /delete /TN "xaxiu-harness-*" /F` for all matching tasks, then removes `state/harness.config.yml`.

## 7. Engine-Specific Guards

| Engine | Guard | Trigger | Action |
|---|---|---|---|
| DeepSeek v4-flash | Auto `--no-thinking` for patches | If packet path matches `*patch*` or `*FIND/REPLACE*` | Add `--no-thinking` to model args |
| Kimi | Multi-domain bundle splitter | If packet contains multiple `domain:` headers (v1 spec) | Split into sub-packets, dispatch each separately |
| All engines | Anchor-fuzzy post-validator | After successful generation, run anchor_fuzzy check on output FIND/REPLACE blocks | If mismatch > 5% (lenient), flag warning, mark as `packet_trap` |
| DeepSeek v4-flash | Packet-trap suppression | If output contains `<gibberish>` boilerplate (regex `^{.*}$`) | Reject, log as `packet_trap`, attempt fallback |

## 8. Auto-Fallback + Log

Procedure:

- On dispatch start, select engine via routing rules → priority → lock → burst.
- If engine fails (timeout > 120s, API error, packet_trap, or anchor mismatch):
   1. Mark current engine as `degraded` in `engine_health.json`.
   2. Pick next engine from ordered list (never same engine), respecting lock/burst.
   3. Append to `state/engine_performance_log.jsonl`:

```jsonl
{"timestamp":"2026-05-17T14:31:00Z","project":"warehouse","packet_path":"packet.md","backend":"deepseek","model":"v4-flash","outcome":"timeout","latency_ms":125000,"fallback_to":"kimi"}
```
- If all engines fail, dispatch is marked `failed` with `outcome="all_fallbacks_exhausted"`.

## 9. Priority Toggle + Burst + Lock

**Override hierarchy (highest to lowest)**:

1. **LOCK** — if engine is locked, all dispatches go to that engine regardless of other settings. Only release via `harness lock --release`.
2. **BURST** — time-bound override to route all to engine X for N minutes. Set via `harness burst <engine> <min>`.
3. **Per-project priority** — defined in adapter YAML (optional). Example: `priority: AVOID` for Kimi in warehouse.
4. **Global priority** — set via `harness priority <engine> <level>`. Stored in `engine_health.json` as `priority` field.
5. **Auto-routing rules** — if no priority override, use adapter routing rules.

**Persistence**: priority, burst, lock states survive in `engine_health.json`. Burst timer runs locally via `harness burst` (schedules a one-shot task to clear after duration). Lock is cleared manually.

## 10. Plugin Interface (ABC)

### Engine

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class EngineResponse:
    success: bool
    text: str
    latency_ms: int
    error: Optional[str] = None

class Engine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dispatch(self, packet_content: str, model: str, extra_args: dict) -> EngineResponse:
        """Send packet to engine, return response."""
```

**Concrete examples**: `DeepSeekEngine`, `KimiEngine`, `AnthropicEngine` implement this.

### StatusBackend

```python
from abc import ABC, abstractmethod

class StatusBackend(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def write(self, project: str, entries: list[dict]) -> None:
        """Append entries to status store."""

    @abstractmethod
    def read(self, project: str, limit: int = 10) -> list[dict]:
        """Read recent status entries."""
```

**Concrete examples**:

**CSV Backend** (`csv_backend.py`):
- `write` appends to CSV file (from `config.csv_path`).
- `read` reads last N lines (with headers).

**Markdown Backend** (`markdown_backend.py`):
- `write` appends a new table row to `status.md`.
- `read` parses last N table rows.

---

*End of architecture specification.*