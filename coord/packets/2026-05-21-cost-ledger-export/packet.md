# ENGINE-COST-LEDGER-EXPORT — daily cost CSV export

## Goal

Operator can't reconcile the dashboard cost panel against actual API
bills (Anthropic/Moonshot/etc) at month-end because the data is locked
inside the jsonl ledger.  Add a daily CSV roll-up to
`coord/cost_daily/YYYY-MM-DD.csv` that's Excel-friendly.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/budget.py`

Find `harness.budget` (existing module).  ADD a new public function:

```python
def export_daily_csv(target_dir: Path | None = None, *, date: str | None = None) -> Path:
    """Write a daily CSV roll-up of the budget ledger.

    Filters ledger entries to *date* (defaults to UTC today).  Columns:
    date, engine, model, requests, input_tokens, output_tokens, est_usd.

    Returns the CSV path written.
    """
    import csv, os
    from datetime import datetime, timezone
    from collections import defaultdict

    target_dir = target_dir or Path("coord") / "cost_daily"
    target_dir.mkdir(parents=True, exist_ok=True)
    iso_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Aggregate by (engine, model)
    agg: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
        lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "est_usd": 0.0}
    )

    try:
        entries = read_ledger() or []
    except Exception:
        entries = []
    for e in entries:
        ts = str(e.get("timestamp") or e.get("ts") or "")[:10]
        if ts != iso_date:
            continue
        engine = str(e.get("engine") or "unknown")
        model = str(e.get("model") or "-")
        bucket = agg[(engine, model)]
        bucket["requests"] += 1
        bucket["input_tokens"] += int(e.get("tokens_in") or 0)
        bucket["output_tokens"] += int(e.get("tokens_out") or e.get("tokens_used") or 0)
        bucket["est_usd"] += float(e.get("cost_usd") or e.get("usd") or 0.0)

    out_path = target_dir / f"{iso_date}.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "engine", "model", "requests",
                         "input_tokens", "output_tokens", "est_usd"])
        for (engine, model), b in sorted(agg.items()):
            writer.writerow([iso_date, engine, model,
                             b["requests"], b["input_tokens"], b["output_tokens"],
                             f"{b['est_usd']:.4f}"])
    return out_path
```

### 2. CLI verb — extend `harness budget` group

Find `@budget_group.command(name="reset")` in `src/harness/cli.py` (the
existing budget group).  Add a NEW sibling command:

```python
@budget_group.command(name="export-daily")
@click.option("--date", default=None,
              help="UTC date YYYY-MM-DD (defaults to today).")
@click.option("--target-dir", default=None, type=click.Path(path_type=Path),
              help="Override output dir (defaults to coord/cost_daily/).")
def budget_export_daily(date: str | None, target_dir: Path | None) -> None:
    """Append-only daily cost roll-up CSV (engine/model/tokens/$ for Excel reconciliation)."""
    from harness.budget import export_daily_csv
    out = export_daily_csv(target_dir=target_dir, date=date)
    click.echo(f"wrote {out}")
```

### 3. Tests

`tests/test_budget_export_daily.py`:

```python
"""Tests for ENGINE-COST-LEDGER-EXPORT."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.budget import export_daily_csv


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _ledger_entries() -> list[dict]:
    return [
        {"timestamp": "2026-05-21T10:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 100, "tokens_out": 200, "cost_usd": 0.01},
        {"timestamp": "2026-05-21T11:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 50, "tokens_out": 100, "cost_usd": 0.005},
        {"timestamp": "2026-05-20T10:00:00Z", "engine": "deepseek", "model": "v4-flash",
         "tokens_in": 1000, "tokens_out": 2000, "cost_usd": 0.10},
    ]


def test_export_daily_csv_filters_to_target_date(tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=_ledger_entries()):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    assert out.exists()
    rows = list(csv.reader(open(out)))
    assert rows[0] == ["date", "engine", "model", "requests",
                       "input_tokens", "output_tokens", "est_usd"]
    # Only kimi/kimi-k2 entries on 2026-05-21
    data_rows = rows[1:]
    assert len(data_rows) == 1
    assert data_rows[0][:3] == ["2026-05-21", "kimi", "kimi-k2"]
    # 2 requests, 150 in, 300 out, $0.015
    assert int(data_rows[0][3]) == 2
    assert int(data_rows[0][4]) == 150
    assert int(data_rows[0][5]) == 300
    assert abs(float(data_rows[0][6]) - 0.015) < 1e-6


def test_export_daily_empty_ledger_writes_header_only(tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=[]):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    rows = list(csv.reader(open(out)))
    assert len(rows) == 1  # header only


def test_export_daily_aggregates_by_engine_and_model(tmp_path: Path) -> None:
    entries = [
        {"timestamp": "2026-05-21T01:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.001},
        {"timestamp": "2026-05-21T02:00:00Z", "engine": "kimi", "model": "kimi-k2",
         "tokens_in": 30, "tokens_out": 40, "cost_usd": 0.003},
        {"timestamp": "2026-05-21T03:00:00Z", "engine": "deepseek", "model": "v4-flash",
         "tokens_in": 100, "tokens_out": 200, "cost_usd": 0.01},
    ]
    with patch("harness.budget.read_ledger", return_value=entries):
        out = export_daily_csv(target_dir=tmp_path, date="2026-05-21")
    data_rows = list(csv.reader(open(out)))[1:]
    assert len(data_rows) == 2  # kimi+kimi-k2 and deepseek+v4-flash
    kimi_row = next(r for r in data_rows if r[1] == "kimi")
    assert int(kimi_row[3]) == 2  # 2 requests


def test_cli_budget_export_daily(runner: CliRunner, tmp_path: Path) -> None:
    with patch("harness.budget.read_ledger", return_value=_ledger_entries()):
        with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
            result = runner.invoke(cli, [
                "budget", "export-daily", "--date", "2026-05-21",
            ])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert "2026-05-21.csv" in result.output
```

## Acceptance

- `python -m pytest tests/test_budget_export_daily.py` — green.
- Full suite stays green.
- `harness budget export-daily --help` shows the verb.

## Constraints

- DO NOT modify `record_dispatch`, `read_ledger`, or `summary`.
- Stdlib only (csv + datetime).
- Keep export_daily_csv under 60 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
