# Packet: Wave A — CLI verb wiring

## Mission
Internals of xaxiu-harness are built (engines, dispatcher, state, secrets, loader, guards) but 11 of 13 CLI verbs in `src/harness/cli.py` print `"not implemented yet"` and exit. Wire each verb to its existing backend, or improve its stub message if the backend isn't built yet. The `dispatch` verb has already been wired by Claude in this session as the canonical pattern.

## Pattern (use this shape for every wired verb)
See `src/harness/cli.py` lines 26-58 (the `dispatch` function). Shape:
1. Validate required inputs; print `error: ...` to stderr and `sys.exit(2)` on missing args.
2. Call the internal function.
3. On success: print result to stdout, `sys.exit(0)`.
4. On failure: print `error: <reason>` to stderr, `sys.exit(1)`.

## Verbs to wire (backend exists)
| Verb | Calls | Notes |
|---|---|---|
| `init -p <project> -t <template>` | `harness.adapters.loader.load_template(template)` | Write rendered template to `adapters/<project>/harness-adapter.yaml`. Refuse to overwrite without `--force`. Currently a dry-run. |
| `status -p <project>` | `harness.adapters.loader.load_project_adapter(project)` then read the adapter's `status_tracking.config.csv_path` | Support `--format csv|json`. Print summary. |
| `engines --list` / `--health` | functions in `harness.state.files` (see `EngineHealth` referenced in `tests/test_dispatcher.py`) | `--list` reads state; `--health` triggers HTTP probe via concrete engine clients. |
| `priority <engine> <level>` | engine-pool state writer in `harness.state.files` | Persist to JSON state. |
| `burst <engine> <duration_min>` | same module | Write expiry timestamp. |
| `lock <engine>` / `lock <engine> --release` | same module | Write/remove lock entry. |

## Verbs to keep stubbed (backend is Wave 3/4/5)
For these, change the message but keep `sys.exit(1)`:
- `observer-tick` → `"observer-tick: backend pending Wave A.2 (observer module not yet built)"`
- `retro` → `"retro: backend pending Wave A.2"`
- `install` → `"install: pending Wave 4 (Windows installer + first-run wizard)"`
- `dashboard-serve` → `"dashboard-serve: pending Wave 3 (FastAPI + WebSocket)"`
- `loops` → `"loops: pending scheduler integration"`

## Discovery step
Before wiring `engines`/`priority`/`burst`/`lock`, read `src/harness/state/files.py` end-to-end. If the required state mutation functions don't exist (function-not-found, not just "untested"), demote those verbs to the stubbed list with message `"<verb>: pending state-layer functions"` — do NOT invent function signatures.

## Acceptance criteria
1. `PYTHONPATH=src python -c "from harness import cli; print(sorted(cli.cli.commands.keys()))"` still prints all 13 verbs.
2. `pytest tests/` still passes (currently 44 tests).
3. Add tests in `tests/test_cli.py` using `click.testing.CliRunner` for each newly-wired verb. Mock the internal calls. Cover: success path, validation-error path, exit codes.
4. `src/harness/cli.py` stays under 500 lines. Factor helpers into `src/harness/cli_helpers.py` if needed.
5. Single commit at the end with message `feat(cli): wire CLI verbs to internal modules (Wave A)`.

## Reference
- Worked example: `src/harness/cli.py:24-58` (dispatch verb, Claude's edit this session)
- `dispatch_packet` signature: `src/harness/engines/dispatcher.py:283`
- Loader functions: `src/harness/adapters/loader.py`
- State files: `src/harness/state/files.py`
- CLAUDE.md "Engine routing rules" — dispatch this packet to **Kimi** per non-V-file routing rule

## Output format
Edits to `src/harness/cli.py` and `tests/test_cli.py`. Optional `src/harness/cli_helpers.py`. No new top-level files. Single commit.
