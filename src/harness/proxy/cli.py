"""CLI commands for the proxy sub-group."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import click

from harness.proxy.state import CircuitState, read_state, write_state


def _pid_path() -> Path:
    return Path(".harness") / "proxy.pid"


def _state_path() -> Path:
    return Path(".harness") / "proxy_state.json"


def _find_process(pid: int) -> bool:
    """Return True if *pid* exists."""
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(1, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _print_status(state_path: Path) -> None:
    try:
        state = read_state(state_path)
    except FileNotFoundError:
        click.echo("Proxy state file not found. Is the proxy running?")
        sys.exit(1)

    click.echo(f"Proxy started: {state.started_at}")
    click.echo(f"Strategy:      {state.routing_strategy}")
    click.echo(f"Total req:     {state.total_requests}")
    click.echo(f"Total errors:  {state.total_errors}")
    click.echo("")
    click.echo(
        f"{'Alias':<8} {'In-Flight':>10} {'State':<12} {'Cooldown':<26} {'Fail':>6} {'Dispatched':>12}"
    )
    for k in state.keys.values():
        cd = k.cooldown_until or ""
        click.echo(
            f"{k.key_alias:<8} {k.in_flight:>10} {k.circuit_state.value:<12} {cd:<26} {k.consecutive_failures:>6} {k.total_dispatched:>12}"
        )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def start(port: int, host: str) -> None:
    pid_path = _pid_path()
    if pid_path.exists():
        existing = int(pid_path.read_text().strip())
        if _find_process(existing):
            click.echo(f"Proxy already running (PID {existing}).")
            return

    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"from harness.proxy.server import serve; serve(host='{host}', port={port})",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    click.echo(f"Proxy started on {host}:{port} (PID {proc.pid})")


def stop() -> None:
    pid_path = _pid_path()
    if not pid_path.exists():
        click.echo("Proxy not running (no PID file).")
        sys.exit(1)
    pid = int(pid_path.read_text().strip())
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    pid_path.unlink()
    click.echo(f"Proxy stopped (PID {pid}).")


def status() -> None:
    import httpx
    try:
        resp = httpx.get("http://127.0.0.1:7879/healthz", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.ConnectError, httpx.TimeoutException):
        click.echo("Proxy not responding on 127.0.0.1:7879. Is it running?")
        sys.exit(1)
    except Exception:
        _print_status(_state_path())
        return

    click.echo(f"Proxy status:   {data['status']}")
    click.echo(f"Pool size:      {data['pool_size']}")
    click.echo(f"In-flight:      {data['in_flight']}")
    click.echo(f"Max concurrent: {data['max_concurrent']}")


def reset_circuit(alias: str) -> None:
    path = _state_path()
    state = read_state(path)
    if alias not in state.keys:
        click.echo(f"Unknown key alias: {alias}")
        sys.exit(1)
    state.keys[alias].circuit_state = CircuitState.CLOSED
    state.keys[alias].consecutive_failures = 0
    state.keys[alias].cooldown_until = None
    state.keys[alias].permanent = False
    write_state(state, path)
    click.echo(f"Circuit for '{alias}' reset.")


def quarantine(alias: str) -> None:
    path = _state_path()
    state = read_state(path)
    if alias not in state.keys:
        click.echo(f"Unknown key alias: {alias}")
        sys.exit(1)
    state.keys[alias].circuit_state = CircuitState.OPEN
    state.keys[alias].permanent = True
    state.keys[alias].cooldown_until = None
    write_state(state, path)
    click.echo(f"Key '{alias}' quarantined (circuit permanently open).")


def unquarantine(alias: str | None = None, all_keys: bool = False) -> tuple[bool, str]:
    """Clear ``permanent`` + ``auto_quarantined_at`` flags on one or all keys.

    Returns ``(ok, message)``.
    """
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


def disable_key(alias: str) -> None:
    path = _state_path()
    state = read_state(path)
    if alias not in state.keys:
        click.echo(f"Unknown key alias: {alias}")
        sys.exit(1)
    state.keys[alias].circuit_state = CircuitState.OPEN
    state.keys[alias].permanent = True
    state.keys[alias].cooldown_until = None
    write_state(state, path)
    click.echo(f"Key '{alias}' disabled.")
