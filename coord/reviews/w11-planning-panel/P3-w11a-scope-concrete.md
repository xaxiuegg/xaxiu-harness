<!-- persona=P3-w11a-scope-concrete status=OK (53721ms) -->

# P3-w11a-scope-concrete

## 1. Top-line summary

`harness agent init --target <path>` must be a zero-interactive, idempotent, sub-3-second bootstrap that gives a fresh Claude Code session an immediate first-dispatch command. The spec below is copy-pasteable into an implementation ticket.

---

## 2. The Concrete Spec

### 2a. CLI Signature

```
harness agent init --target <path> [--project-type <type>] [--adapter-name <name>] [--dry-run] [--non-interactive]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--target` | **yes** | — | Directory to bootstrap. Created if nonexistent. Error if exists and is not a directory. |
| `--project-type` | no | `python` | Template selector. Accepted values: `python`, `node`, `generic`. |
| `--adapter-name` | no | derived from `--target` basename (PascalCase + `Adapter`) | Class name for `adapter.py` |
| `--dry-run` | no | `false` | Print every file path + content to stdout; write nothing. |
| `--non-interactive` | no | `false` | Suppress all prompts; overwrite nothing silently. When `false`, interactive sessions get `[y/N]` prompts on collision. |

### 2b. File Tree Written

Given `harness agent init --target ./my-project` (project-type=python, basename=my-project → `MyProjectAdapter`):

```
my-project/
├── .env
├── .gitignore                    # only if not already present
├── adapter.py
├── CLAUDE.md                     # appended if exists; created if not
└── .harness/
    ├── config.json
    ├── run_count                 # literal integer: 0
    ├── dispatched/               # empty dir; .gitkeep
    │   └── .gitkeep
    └── STATUS.csv                # header row only
```

### 2c. Literal File Contents

**`.env`**
```bash
# harness-agent-secrets  —  never commit this file
HARNESS_OPENAI_API_KEY=
HARNESS_DEEPSEEK_API_KEY=
HARNESS_GEMINI_API_KEY=
# HARNESS_ENCRYPT_WITH_DPAPI=1   # Windows-only: uncomment to store secrets in DPAPI
```

**`.gitignore`** (created only if absent)
```
.env
.harness/
__pycache__/
*.pyc
```

**`adapter.py`**
```python
"""Default adapter for my-project — edit project_name and engines as needed."""

from harness.adapters.scaffold import BaseAdapter

ADAPTER_NAME = "MyProjectAdapter"
PROJECT_NAME = "my-project"

DEFAULT_ENGINES = {
    "openai": {
        "model": "gpt-4o",
        "api_key_env": "HARNESS_OPENAI_API_KEY",
        "max_tokens": 4096,
    },
    "deepseek": {
        "model": "deepseek-chat",
        "api_key_env": "HARNESS_DEEPSEEK_API_KEY",
        "max_tokens": 8192,
    },
}


class MyProjectAdapter(BaseAdapter):
    def resolve_engine(self, request):
        return request.engine or "openai"

    def build_packet(self, request, engine):
        return {
            "model": DEFAULT_ENGINES[engine]["model"],
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": DEFAULT_ENGINES[engine]["max_tokens"],
        }
```

**`CLAUDE.md`** (appended section, only if `[harness:agent-init]` marker absent)
```markdown

---
<!-- harness:agent-init -->
# Harness Agent Instructions

Dispatch work to offload engines:

```bash
harness dispatch --target . --engine openai "your prompt here"
```

Retrieve a full result by ID:

```bash
harness retrieve <dispatch_id> --scope full
```

Check remaining budget:

```bash
harness budget --target . --show
```

> Do NOT edit `.harness/config.json` or `adapter.py` without also updating STATUS.csv history.
```

**`.harness/config.json`**
```json
{
  "adapter_module": "adapter",
  "adapter_class": "MyProjectAdapter",
  "project_name": "my-project",
  "created_at": "<ISO-8601 UTC>",
  "init_version": "w11"
}
```

**`.harness/run_count`**
```
0
```

**`.harness/STATUS.csv`**
```
timestamp,dispatch_id,engine,tokens_used,duration_ms,status,error
```

**`.harness/dispatched/.gitkeep`** — empty file.

### 2d. Idempotency Contract

| Scenario | Behavior |
|---|---|
| Target dir doesn't exist | Create it recursively. |
| `.harness/` missing | Full create. |
| `.harness/config.json` exists | **Error (exit 2)** unless `--non-interactive`. Interactive → `[y/N]` to re-initialize (backs up existing config to `.harness/config.json.bak`). |
| `adapter.py` exists | **Skip with warning** to stderr. Never overwrite. |
| `CLAUDE.md` exists | Scan for `<!-- harness:agent-init -->` marker. If present → **skip**. If absent → **append** section. Never overwrite. |
| `.env` exists | **Skip** silently (operator may have real secrets). |
| `.gitignore` exists | **Skip** silently. |
| `STATUS.csv` exists | **Error (exit 3)** — data file; operator must merge manually. |
| `--dry-run` | Print all paths + contents to stdout. Exit 0. Touch nothing. |

### 2e. Error States

| Condition | Exit Code | Message |
|---|---|---|
| `--target` is not a directory and not creatable | 1 | `ERROR: --target path exists and is not a directory: {path}` |
| Permission denied writing to target | 1 | `ERROR: cannot write to {path}: {os_error}` |
| `config.json` collision, non-interactive | 2 | `ERROR: .harness/config.json already exists. Re-run interactively to overwrite.` |
| `STATUS.csv` collision | 3 | `ERROR: .harness/STATUS.csv already exists and contains dispatch history. Merge manually.` |
| Unknown `--project-type` | 4 | `ERROR: unknown project type '{value}'. Accepted: python, node, generic` |
| `--dry-run` | 0 | Print tree + contents to stdout. |

All warnings go to **stderr**. All file contents in `--dry-run` go to **stdout** (pipe-friendly).

### 2f. Success Message & Teach-Next

On clean exit, print to **stdout**:

```
✓ Initialized harness agent project at {target}/

  Created:
    .env                          ← fill in API keys
    adapter.py                    ← edit engines as needed
    CLAUDE.md                     ← agent instructions (auto-read by Claude Code)
    .harness/config.json          ← project metadata
    .harness/STATUS.csv           ← dispatch ledger

  Next step — dispatch your first packet:

    harness dispatch --target . --engine openai "Summarize the README in 3 sentences"

  Then retrieve the full result:

    harness retrieve <id> --scope full

  Check remaining budget anytime:

    harness budget --target . --show
```

---

## 3. Two Open Questions

1. **Secrets bootstrapping on first dispatch:** If `.env` values are blank at init time, should `harness dispatch` fail fast with `ERROR: HARNESS_OPENAI_API_KEY is empty in .env` (recommended) or fall back to DPAPI/system-env silently? The `.env`-first contract in W11-DPAPI-CROSS-PLATFORM suggests fail-fast, but the spec should state this explicitly.

2. **`adapter.py` vs package:** Should the adapter be a single file (`adapter.py`) or a package (`adapter/__init__.py`)? A single file is simpler for W11, but if multi-file adapters are on the roadmap (e.g., separate `prompts.py`, `parsers.py`), now is the time to decide. Recommendation: ship single-file, document the upgrade path.

---

## 4. Alignment Check

| Action | Details |
|---|---|
| **Split W11-CLAUDE-MD-TEMPLATE out of Wave 11-A** | `agent init` already writes a CLAUDE.md template. Shipping W11-CLAUDE-MD-TEMPLATE separately means two competing templates. Merge it: `init` uses the canonical template, and `CLAUDE-MD-TEMPLATE` becomes the "standalone template library" that `init` imports from. |
| **Reorder: W11-ADAPTER-VALIDATE-JSON before Wave 11-B** | `init` writes `adapter.py` that users will edit. If validation ships after the SDK, agents dispatch broken adapters and get opaque errors. Ship validate+JSON early so `init` can print a "validate your edits" follow-up hint. |
| **W11-HIDE-ADVANCED-VERBS is a prereq** | `harness agent init` surfaces in `--help`. If advanced verbs aren't hidden yet, the help output will be noisy. Ship hide-advanced first or gate `agent` as a hidden subgroup that reveals on first use. |
| **Defer W11-PER-CHECK-LATENCY-OBSERVABILITY** | No dependency on init. Clean it out of the critical path. |
