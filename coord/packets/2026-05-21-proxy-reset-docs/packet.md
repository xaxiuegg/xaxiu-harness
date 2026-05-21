# PROXY-RESET-DOCS — `harness proxy unquarantine` + recovery docs

## Goal

The proxy state machine has 4 "key disabled" pathways:
1. Circuit breaker OPEN (auto-recovers after cooldown)
2. AUTO-QUARANTINE-KEY (`permanent=True`, set by flap detection)
3. Operator `harness proxy quarantine <alias>` (also `permanent=True`)
4. Kill conditions firing L4 (stops loop, not key-specific)

Existing `harness proxy reset-circuit` only resets state (1). States (2)
and (3) are silently stuck — no documented recovery verb.  Operators
read the docs and assume `reset-circuit` does it all.

Fix: add `harness proxy unquarantine` and document the 4-pathway map.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/proxy/cli.py`

Find the existing `reset_circuit` function in `src/harness/proxy/cli.py`
(or wherever the proxy CLI helpers live).  Add a sibling:

```python
def unquarantine(alias: str | None = None, all_keys: bool = False) -> tuple[bool, str]:
    """Clear ``permanent`` + ``auto_quarantined_at`` flags on one or all keys.

    Returns ``(ok, message)``.
    """
    from harness.proxy.state import read_state, write_state, CircuitState
    state = read_state()
    if not all_keys and not alias:
        return False, "specify --alias <KEY> or --all"
    cleared: list[str] = []
    for key_alias, ks in state.keys.items():
        if not all_keys and key_alias != alias:
            continue
        if ks.permanent or ks.auto_quarantined_at is not None:
            ks.permanent = False
            ks.auto_quarantined_at = None
            ks.consecutive_failures = 0
            ks.circuit_state = CircuitState.CLOSED
            ks.cooldown_until = None
            cleared.append(key_alias)
    if not cleared:
        return False, "no quarantined keys matched"
    write_state(state)
    return True, f"unquarantined: {', '.join(cleared)}"
```

### 2. New CLI subcommand in cli.py

In `src/harness/cli.py`, find `@proxy_group.command(name="quarantine")`
(around the proxy block).  Add a NEW sibling AFTER it:

```python
@proxy_group.command(name="unquarantine")
@click.option("--alias", default=None, help="Specific key alias to unquarantine.")
@click.option("--all", "all_keys", is_flag=True,
              help="Clear quarantine on ALL keys.")
def proxy_unquarantine(alias: str | None, all_keys: bool) -> None:
    """Clear permanent-quarantine state set by --quarantine or AUTO-QUARANTINE-KEY."""
    from harness.proxy.cli import unquarantine
    ok, msg = unquarantine(alias=alias, all_keys=all_keys)
    click.echo(msg)
    sys.exit(0 if ok else 1)
```

### 3. Recovery doc — `spec/proxy-recovery.md`

```markdown
# Proxy key disable states — recovery map (2026-05-21)

The 4-key proxy can disable an API key in 4 ways.  Each has its own
reset path.

| State | Trigger | Reset verb | Notes |
|---|---|---|---|
| circuit_state OPEN | 3 consecutive failures | `harness proxy reset-circuit <alias>` OR wait for cooldown_until | Auto-recovers when cooldown elapses |
| permanent + auto_quarantined_at | 3 flaps in 60min (AUTO-QUARANTINE-KEY) | `harness proxy unquarantine <alias>` | L4 escalation file at coord/observer/escalations/flap_*.json |
| permanent + (no auto_quarantined_at) | Operator ran `harness proxy quarantine <alias>` | `harness proxy unquarantine <alias>` | Manual reset only — no automatic recovery |
| loop_status="stopped" | kill_conditions L4 fired | `harness loop start` re-arms; check coord/dev_loop/escalations[] | Not key-specific; the whole loop halts |

For a single-shot "clear everything" recovery:

```
harness proxy unquarantine --all
harness proxy reset-circuit --key-id ALL   # if separate
harness loop start --cadence-minutes 30
```
```

### 4. Tests

`tests/test_proxy_unquarantine.py`:

```python
"""Tests for PROXY-RESET-DOCS — unquarantine verb."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.proxy.cli import unquarantine
from harness.proxy.state import CircuitState, KeyState, ProxyState


def _make_state(keys: dict[str, dict]) -> ProxyState:
    return ProxyState(
        schema_version=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        keys={
            alias: KeyState(
                key_alias=alias,
                permanent=info.get("permanent", False),
                auto_quarantined_at=info.get("auto_quarantined_at"),
                consecutive_failures=info.get("failures", 0),
                circuit_state=info.get("circuit", CircuitState.CLOSED),
            )
            for alias, info in keys.items()
        },
    )


def test_unquarantine_requires_alias_or_all() -> None:
    with patch("harness.proxy.cli.read_state",
               return_value=_make_state({"k1": {"permanent": True}})), \
         patch("harness.proxy.cli.write_state") as _:
        ok, msg = unquarantine()
    assert ok is False
    assert "--alias" in msg or "--all" in msg


def test_unquarantine_clears_specific_key() -> None:
    state = _make_state({
        "k1": {"permanent": True, "auto_quarantined_at": "2026-05-21T01:00:00Z",
               "failures": 5, "circuit": CircuitState.OPEN},
        "k2": {"permanent": False},
    })
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state") as mock_w:
        ok, msg = unquarantine(alias="k1")
    assert ok is True
    assert "k1" in msg
    # k1 cleared; k2 untouched
    assert state.keys["k1"].permanent is False
    assert state.keys["k1"].auto_quarantined_at is None
    assert state.keys["k1"].circuit_state == CircuitState.CLOSED
    assert state.keys["k1"].consecutive_failures == 0


def test_unquarantine_all_clears_every_key() -> None:
    state = _make_state({
        "k1": {"permanent": True},
        "k2": {"permanent": True, "auto_quarantined_at": "x"},
        "k3": {"permanent": False},
    })
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state"):
        ok, msg = unquarantine(all_keys=True)
    assert ok is True
    assert "k1" in msg and "k2" in msg
    # k3 wasn't quarantined so not included
    assert "k3" not in msg


def test_unquarantine_no_matches_returns_false() -> None:
    state = _make_state({"k1": {"permanent": False}})
    with patch("harness.proxy.cli.read_state", return_value=state), \
         patch("harness.proxy.cli.write_state"):
        ok, msg = unquarantine(all_keys=True)
    assert ok is False
    assert "no quarantined" in msg.lower()


def test_cli_unquarantine_alias_arg() -> None:
    runner = CliRunner()
    with patch("harness.proxy.cli.unquarantine",
               return_value=(True, "unquarantined: k1")):
        result = runner.invoke(cli, ["proxy", "unquarantine", "--alias", "k1"])
    assert result.exit_code == 0
    assert "unquarantined: k1" in result.output


def test_cli_unquarantine_no_match_exits_1() -> None:
    runner = CliRunner()
    with patch("harness.proxy.cli.unquarantine",
               return_value=(False, "no quarantined keys matched")):
        result = runner.invoke(cli, ["proxy", "unquarantine", "--all"])
    assert result.exit_code == 1
```

## Acceptance

- `python -m pytest tests/test_proxy_unquarantine.py` — green.
- Full suite stays green.
- `harness proxy --help` shows the new `unquarantine` verb.
- `spec/proxy-recovery.md` exists with the 4-state table.

## Constraints

- DO NOT change `reset_circuit` or `quarantine` behaviour.
- DO NOT touch the circuit-breaker logic in `proxy/circuit.py`.
- Stdlib only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
