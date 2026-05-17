# Packet: Wave 1 / C — CLI scaffolding (Click)

## Mission
Produce `src/harness/cli.py` — Click-based CLI with all 13 verbs from `spec/v1-architecture.md` §3, each stubbed to print parsed args + return "not implemented yet" cleanly. Logic comes in Wave 2.

## Required verbs

| Verb | Options/args | Stub behavior |
|---|---|---|
| `dispatch` | `--project`, `--packet`, `--backend`, `--model`, `--force-engine` | Print parsed args, exit 0 |
| `status` | `--project`, `--report` flag, `--format [csv\|json]` | Print stub message |
| `observer-tick` | `--project` | Print stub |
| `retro` | `--project`, `--date YYYY-MM-DD` | Print stub |
| `install` | `--uninstall` flag | Print stub |
| `init` | `--project`, `--template [warehouse-style\|generic-coding\|writing-content\|research-comparison\|solo-dev\|basic]` | Print "would create template X for project Y" |
| `env` | `--show-set` flag | Read KIMI_API_KEY / DEEPSEEK_API_KEY / ANTHROPIC_API_KEY env vars and print only "SET"/"MISSING" for each — NEVER echo values |
| `dashboard-serve` | `--port INTEGER (default 7878)` | Print stub |
| `loops` | `--project`, `--add NAME::COMMAND::CRON`, `--remove NAME` | Print stub |
| `engines` | `--list`, `--health`, `--priority ENGINE PRIORITY`, `--burst ENGINE DURATION`, `--lock ENGINE`, `--release` | Print stub |
| `priority` | `ENGINE [HIGH\|NORMAL\|AVOID]` positional | Print stub |
| `burst` | `ENGINE DURATION_MIN` positional | Print stub |
| `lock` | `ENGINE`, `--release` flag | Print stub |

## Exit codes
- 0 = success
- 1 = generic error
- 2 = engine failure (with fallback occurred)
- 3 = lock conflict

## CRITICAL security requirement: env verb
The `env` command MUST use this exact pattern for each key (do NOT deviate):

```python
import os
key_name = "KIMI_API_KEY"
val = os.environ.get(key_name)
if val:
    click.echo(f"{key_name}: SET")
else:
    click.echo(f"{key_name}: MISSING")
```

NEVER write `click.echo(f"{key_name}: {val}")` or any pattern using f-string interpolation of the value, even with fallbacks. Even `val or 'MISSING'` is unsafe if val happens to be empty string vs None vs the actual key — the actual key would print. Use the explicit `if val:` check.

## Required structure
- Entry point: `main()` registered as console_script in `pyproject.toml` (already wired as `harness = "harness.cli:main"`)
- Use `@click.group()` decorated `cli` function as the root group, with `main = cli` alias
- Each command: `@cli.command()` decorator + `@click.option()` for each option + docstring (used for `harness <verb> --help`)
- Each stub: log parsed args via `click.echo` (never `print`), return appropriate exit code via `sys.exit()` or `ctx.exit()`
- Module docstring explaining the package
- Target 200-300 lines including docstrings
- Type-hint function signatures

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/cli.py`. Standard import order: stdlib → third-party (click) → local. No external deps beyond click.

## Reference
- v1 spec §3 (CLI command surface table) at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1.1 spec §1 surface map (operator experience expectations)
- Existing `pyproject.toml` at `D:/Projects/xaxiu-harness/pyproject.toml` (entry point already wired)
