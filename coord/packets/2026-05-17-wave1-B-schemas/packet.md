# Packet: Wave 1 / B — Pydantic adapter schemas

## Mission
Produce `src/harness/adapters/schema.py` — Pydantic v2 models for the xaxiu-harness adapter YAML schema defined in `spec/v1-architecture.md` §2 and `spec/v1.1-operator-experience.md` §2.

## Required models
1. `RoutingAction` — fields: `backend` (Literal["deepseek", "kimi", "anthropic", "burst"]), `model` (str, optional), `extra_args` (dict[str, Any], default empty)
2. `RoutingRule` — fields: `if_` (str, aliased "if"), `then` (RoutingAction), `reason` (str, optional)
3. `StatusTrackingConfig` — fields: `backend` (Literal["csv", "markdown", "jira", "linear"]), `config` (dict[str, Any])
4. `ObserverConfig` — fields: `enabled` (bool, default True), `cadence_minutes` (int, default 30, constraints ge=5 le=120), `daily_retro_time` (str, default "17:00", HH:MM regex), `flag_patterns` (list[str], default [".*FAIL.*", ".*BLOCKER.*"])
5. `ScheduledTask` — fields: `cron` (str), `command` (str), `idempotent` (bool, default True)
6. `AdapterConfig` — fields: `name` (str), `project_root` (str), `status_tracking` (StatusTrackingConfig), `observer` (ObserverConfig), `routing_rules` (list[RoutingRule], default []), `scheduled_tasks` (list[ScheduledTask], default [])

## Required validators
- `name`: alphanumeric + underscore + hyphen only, max length 64
- `project_root`: absolute path OR contains `{{PROJECT_ROOT}}` placeholder; reject `..` traversal patterns
- `cron`: must parse as 5-field cron expression (use simple regex; full validation in Wave 2)
- `daily_retro_time`: HH:MM 24-hour format
- `command`: must start with `"harness "`
- `routing_rules[].if_`: max length 256 to prevent regex DoS

## CRITICAL security requirements
- Use `yaml.safe_load` exclusively; NEVER `yaml.load`
- No `eval`/`exec` anywhere
- Path validation must prevent `../` traversal in `project_root`
- Reject shell metacharacters (`;`, `|`, `&`, backticks, `$()`) in `command` field unless they're inside quoted arguments
- All string fields capped at reasonable max_length (defaults: 4096) to prevent DoS
- Reject `flag_patterns` regex that compiles to catastrophic backtracking patterns (basic check: pattern length <512)

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/adapters/schema.py`. Use Pydantic v2 syntax (`model_config`, `field_validator`, `model_validator`). Include module docstring + class docstrings. Target 150-250 lines. Type-hint everything. Import only from stdlib + pydantic + yaml.

Also provide a `load_adapter(path: str) -> AdapterConfig` helper function at the bottom of the file that: reads the YAML file, calls `yaml.safe_load`, validates against `AdapterConfig`, and returns the instance. Raise clear ValueError on validation failure.

## Reference
- v1 spec §2 (adapter YAML schema, Pydantic model equivalent table) at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1.1 spec §4.2 (validation pipeline) at `D:/Projects/xaxiu-harness/spec/v1.1-operator-experience.md`
- v1.1 spec §2.1-2.5 (5 templates show expected YAML shapes)
