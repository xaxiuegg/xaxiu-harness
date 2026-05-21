# Packet: BUDGET-METER — Dispatch budget + per-engine cost ledger

## Mission

Track dispatch costs across engines (Kimi-CLI subscription, Kimi-API per-call, DeepSeek per-call, Anthropic per-call) so the operator can answer "how much have I burned this month?" without scrolling jsonl logs. Surface via `harness budget` CLI verb group with subcommands for ledger inspection + budget enforcement.

Creativity-tick idea from 2026-05-20 (score 82). Promoted from parked → queued under the dev-manager directive 2026-05-21.

## In-scope NEW files

- `src/harness/budget.py` — Pydantic `CostEntry` schema + ledger reader/writer (atomic) + per-engine pricing table + `record_dispatch(task_id, engine, model, latency_ms, input_tokens, output_tokens)` API + budget-cap enforcement
- `tests/test_budget.py` — schema validation + roundtrip + pricing math + budget cap trips + CLI smoke

## In-scope MODIFY files

- `src/harness/cli.py` — add `@cli.group(name="budget")` with subcommands: `show`, `summary`, `set-cap`, `reset`. ≤40 LOC; delegate logic to `harness.budget`.

## Pricing table (use as defaults; operator can override via env)

```python
# src/harness/budget.py
PRICING_USD_PER_M_TOKENS: dict[str, dict[str, float]] = {
    # input, output (per 1M tokens, USD)
    "kimi":         {"input":  0.0,  "output": 0.0},   # subscription, marginal $0
    "kimi-api":     {"input":  0.15, "output": 2.50},  # Moonshot K2 pricing
    "deepseek":     {"input":  0.27, "output": 1.10},  # v4-flash
    "deepseek-pro": {"input":  0.55, "output": 2.19},  # v4-pro
    "anthropic":    {"input":  3.00, "output": 15.00}, # Sonnet baseline
}
```

Operator overrides via `HARNESS_BUDGET_PRICING_JSON` env var (JSON string).

## CostEntry schema

```python
from pydantic import BaseModel, ConfigDict, Field

class CostEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: str               # iso8601 UTC
    task_id: str
    engine: str
    model: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
```

## Ledger storage

`coord/dev_loop/budget_ledger.jsonl` — append-only jsonl, one CostEntry per line.

Atomic append via `open(path, "ab")` + `os.fsync` (jsonl_log pattern).

Add to `.gitignore`.

## API

```python
# src/harness/budget.py
def record_dispatch(
    *,
    task_id: str,
    engine: str,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    ledger_path: Path | None = None,
) -> CostEntry: ...

def read_ledger(ledger_path: Path | None = None) -> list[CostEntry]: ...

def summary(
    ledger_path: Path | None = None,
    since_iso: str | None = None,
) -> dict[str, dict[str, float]]:
    """Return {engine: {dispatches, total_cost_usd, total_input_tokens, total_output_tokens}}."""

def total_spent(
    ledger_path: Path | None = None,
    since_iso: str | None = None,
) -> float: ...

def check_cap(
    monthly_cap_usd: float | None = None,
    ledger_path: Path | None = None,
) -> tuple[bool, float, float]:
    """Returns (within_cap, spent_this_month, cap)."""
```

## CLI

```python
@cli.group(name="budget")
def budget_group() -> None: ...

@budget_group.command(name="show")
@click.option("--engine", default=None)
@click.option("--since", default=None, help="ISO timestamp filter")
def budget_show(engine, since): ...   # tabular ledger output

@budget_group.command(name="summary")
@click.option("--since", default="this-month")
def budget_summary(since): ...        # per-engine totals + grand total

@budget_group.command(name="set-cap")
@click.argument("amount_usd", type=float)
def budget_set_cap(amount_usd): ...   # write to coord/dev_loop/budget_cap.json

@budget_group.command(name="reset")
@click.option("--force", is_flag=True)
def budget_reset(force): ...          # archive ledger + start fresh
```

## Tests required

1. CostEntry rejects negative tokens / negative cost.
2. record_dispatch computes cost correctly from pricing table.
3. record_dispatch handles unknown engine with cost=0 + warning log.
4. read_ledger handles empty file / missing file (returns []).
5. summary aggregates correctly across multiple entries.
6. check_cap returns (False, ...) when over cap.
7. CLI show / summary / set-cap / reset smokes.
8. Atomic-write robustness (mock os.replace to fail; original intact).
9. `since_iso` filter works for "this-month" + arbitrary ISO date.

Target ≥10 new tests.

## Acceptance criteria

1. `harness budget --help` lists 4 subcommands.
2. `harness budget summary` against an empty ledger prints "(no dispatches)".
3. `record_dispatch(engine='kimi-api', input_tokens=1000000, output_tokens=200000)` produces a CostEntry with `cost_usd ≈ 0.15 + 0.50 = 0.65`.
4. `python -m pytest tests/ -q` shows ≥488 + new tests, all green.
5. Single commit: `feat(budget): dispatch budget meter + per-engine cost ledger (BUDGET-METER)`.

## Output format

1 new module + 1 new test file + 1 cli.py modification (≤40 LOC) + 1 `.gitignore` entry + 1 commit.
