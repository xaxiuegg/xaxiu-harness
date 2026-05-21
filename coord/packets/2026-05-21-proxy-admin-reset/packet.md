# PROXY-ADMIN-RESET — `harness proxy reset-circuit` + `disable-key` admin verbs

## Goal

`src/harness/proxy/` ships a 4-key circuit breaker (v2/A), but the
operator has no CLI verb to manually re-enable a quarantined key after
fixing the underlying issue (e.g. rotated credential).  This wave adds
two minimal admin verbs.

NOTE: read `src/harness/proxy/cli.py` BEFORE patching — if `reset-circuit`
already exists (it was hinted in CLAUDE.md), this wave only adds
`disable-key`.  Don't duplicate.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. Read first

Run a quick `grep -nE "@proxy_group\.command\(name=" src/harness/proxy/cli.py`
(or check `src/harness/cli.py` if proxy commands live there) to enumerate
existing proxy subcommands.  Implement only the missing ones from this list:

- `harness proxy reset-circuit` — clears the circuit-breaker state for
  one key (or all keys with `--all`).
- `harness proxy disable-key <id>` — manually marks a key as
  quarantined so the breaker won't route to it.

If both already exist, this packet is a no-op — just verify and exit.

### 2. Implement missing verbs

The proxy state file is `.harness/proxy_state.json`.  Schema (see
`src/harness/proxy/state.py` if present):

```json
{
  "keys": {
    "k1": {"status": "healthy", "consecutive_failures": 0, "quarantined_until": null},
    "k2": ...
  },
  "circuit": {"open": false, "opened_at": null}
}
```

For `reset-circuit`:

```python
@proxy_group.command(name="reset-circuit")
@click.option("--key-id", default=None, help="Reset one key; default is all keys.")
def proxy_reset_circuit(key_id: str | None) -> None:
    """Clear circuit-breaker state for a key (or all keys) so dispatch can resume."""
    from harness.proxy.state import load_state, save_state
    state = load_state()
    if key_id:
        if key_id not in state.get("keys", {}):
            click.echo(f"error: no such key {key_id}", err=True)
            sys.exit(1)
        k = state["keys"][key_id]
        k["status"] = "healthy"
        k["consecutive_failures"] = 0
        k["quarantined_until"] = None
        click.echo(f"reset: {key_id}")
    else:
        for kid, k in state.get("keys", {}).items():
            k["status"] = "healthy"
            k["consecutive_failures"] = 0
            k["quarantined_until"] = None
        state["circuit"] = {"open": False, "opened_at": None}
        click.echo(f"reset: all keys + circuit closed")
    save_state(state)
```

For `disable-key`:

```python
@proxy_group.command(name="disable-key")
@click.argument("key_id")
def proxy_disable_key(key_id: str) -> None:
    """Manually quarantine a key so the proxy won't route to it."""
    from harness.proxy.state import load_state, save_state
    state = load_state()
    if key_id not in state.get("keys", {}):
        click.echo(f"error: no such key {key_id}", err=True)
        sys.exit(1)
    state["keys"][key_id]["status"] = "quarantined"
    state["keys"][key_id]["quarantined_until"] = "manual"
    save_state(state)
    click.echo(f"disabled: {key_id}")
```

If `load_state` / `save_state` helpers don't exist in
`harness.proxy.state`, use direct JSON I/O from `.harness/proxy_state.json`
with atomic write (tempfile + os.replace).  Default the state file to
`{"keys": {}, "circuit": {"open": False}}` when missing.

### 3. Tests

New file `tests/test_proxy_admin_cli.py`:

```python
"""Tests for proxy admin verbs (reset-circuit + disable-key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_state(tmp_path: Path, state: dict) -> None:
    p = tmp_path / ".harness" / "proxy_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), encoding="utf-8")


def test_reset_circuit_single_key(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "keys": {"k1": {"status": "quarantined", "consecutive_failures": 5, "quarantined_until": "2099-01-01"}},
            "circuit": {"open": True, "opened_at": "2026-05-21T00:00:00Z"},
        })
        result = runner.invoke(cli, ["proxy", "reset-circuit", "--key-id", "k1"])
        assert result.exit_code == 0, result.output
        loaded = json.loads((iso_path / ".harness" / "proxy_state.json").read_text())
        assert loaded["keys"]["k1"]["status"] == "healthy"
        assert loaded["keys"]["k1"]["consecutive_failures"] == 0


def test_reset_circuit_all_keys(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "keys": {
                "k1": {"status": "quarantined", "consecutive_failures": 5, "quarantined_until": "2099"},
                "k2": {"status": "quarantined", "consecutive_failures": 3, "quarantined_until": "2099"},
            },
            "circuit": {"open": True, "opened_at": "2026-05-21T00:00:00Z"},
        })
        result = runner.invoke(cli, ["proxy", "reset-circuit"])
        assert result.exit_code == 0, result.output
        loaded = json.loads((iso_path / ".harness" / "proxy_state.json").read_text())
        assert loaded["keys"]["k1"]["status"] == "healthy"
        assert loaded["keys"]["k2"]["status"] == "healthy"
        assert loaded["circuit"]["open"] is False


def test_disable_key_marks_quarantined(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {
            "keys": {"k1": {"status": "healthy", "consecutive_failures": 0, "quarantined_until": None}},
            "circuit": {"open": False},
        })
        result = runner.invoke(cli, ["proxy", "disable-key", "k1"])
        assert result.exit_code == 0, result.output
        loaded = json.loads((iso_path / ".harness" / "proxy_state.json").read_text())
        assert loaded["keys"]["k1"]["status"] == "quarantined"


def test_reset_circuit_unknown_key(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {"keys": {}, "circuit": {"open": False}})
        result = runner.invoke(cli, ["proxy", "reset-circuit", "--key-id", "nope"])
        assert result.exit_code == 1
        assert "no such key" in result.output


def test_disable_key_unknown(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        _seed_state(iso_path, {"keys": {}, "circuit": {"open": False}})
        result = runner.invoke(cli, ["proxy", "disable-key", "nope"])
        assert result.exit_code == 1
```

## Acceptance

- `python -m pytest tests/test_proxy_admin_cli.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- `harness proxy --help` shows the two verbs.

## Constraints

- DO NOT modify dispatcher, circuit-breaker logic, or proxy.app.
- Use Click's isolated_filesystem(temp_dir=tmp_path) inside tests so the
  state file doesn't leak into the repo.

## Engine guidance

Single-file CLI extension + 1 new test file.  swarm/kimi or
swarm/kimi-api.  Timeout 420s.
