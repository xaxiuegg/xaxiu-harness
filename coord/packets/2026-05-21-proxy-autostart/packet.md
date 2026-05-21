# PROXY-AUTOSTART — auto-start v2/A proxy from `harness coord run`

## Goal

When the operator runs `harness coord run --spec ...`, the v2 architecture
expects a 4-key Kimi proxy listening on `localhost:7879` (see
`spec/multi-agent-harness-architecture.md` §3.A and `src/harness/proxy/`).
Today the operator must remember to launch the proxy as a separate
foreground process before starting any coord run.  This wave makes
`harness coord run` auto-start the proxy if it isn't already listening,
and clean it up on exit.

## Scope (in-place edit; kimi-cli is fine, kimi-api with FIND/REPLACE also fine)

### 1. New module `src/harness/proxy/lifecycle.py`

A tiny, side-effect-free helper module.

```python
"""Proxy lifecycle helpers — start/stop the v2 stateful proxy as a child process."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 7879


def is_proxy_listening(host: str = DEFAULT_PROXY_HOST, port: int = DEFAULT_PROXY_PORT,
                       timeout: float = 0.5) -> bool:
    """Return True if a TCP socket can connect to host:port within *timeout*."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def start_proxy(host: str = DEFAULT_PROXY_HOST, port: int = DEFAULT_PROXY_PORT,
                wait_seconds: float = 5.0) -> Optional[subprocess.Popen]:
    """Spawn the proxy as a child process; return Popen handle.

    Returns None if the proxy is already listening.  Polls up to wait_seconds
    for the spawned process to become reachable.
    """
    if is_proxy_listening(host, port):
        return None

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "harness.proxy.app:app",
         "--host", host, "--port", str(port), "--log-level", "warning"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Poll for readiness
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_proxy_listening(host, port):
            return proc
        if proc.poll() is not None:
            # Process died before becoming reachable
            return None
        time.sleep(0.1)
    # Timed out; kill and return None so caller can decide
    try:
        proc.terminate()
    except Exception:
        pass
    return None


def stop_proxy(proc: Optional[subprocess.Popen]) -> None:
    """Terminate the proxy child process if any; idempotent on None / dead procs."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception:
        pass
```

### 2. Wire into `cli.py::coord_run`

Locate the existing `coord_run` command (around line 1280 — search for
`@coord_group.command(name="run")`).

Add a `--proxy` Click option:

```python
@click.option("--proxy", type=click.Choice(["auto", "off", "external"]),
              default="auto",
              help="Auto-start the v2 proxy ('auto'), use a running one ('external'), or skip ('off').")
```

At the top of the command body (after option parsing), import the helper
and start the proxy:

```python
from harness.proxy import lifecycle as proxy_lifecycle

proxy_proc = None
if proxy == "auto":
    proxy_proc = proxy_lifecycle.start_proxy()
    if proxy_proc is not None:
        click.echo(f"proxy: started (pid={proxy_proc.pid})")
    elif proxy_lifecycle.is_proxy_listening():
        click.echo("proxy: already running")
    else:
        click.echo("proxy: WARNING — failed to start; continuing", err=True)
elif proxy == "external":
    if not proxy_lifecycle.is_proxy_listening():
        click.echo("proxy: --proxy=external but no proxy listening on 7879", err=True)
        sys.exit(1)
```

Use a `try/finally` so the proxy is stopped on exit:

```python
try:
    # ... existing coord_run body ...
finally:
    if proxy_proc is not None:
        proxy_lifecycle.stop_proxy(proxy_proc)
```

### 3. Tests

New file `tests/test_proxy_lifecycle.py`:

```python
"""Tests for harness.proxy.lifecycle."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from harness.proxy import lifecycle


def test_is_proxy_listening_returns_false_on_no_listener() -> None:
    # Use an unlikely port that nothing should be listening on
    assert lifecycle.is_proxy_listening(port=63999, timeout=0.1) is False


def test_is_proxy_listening_returns_true_when_socket_accepts() -> None:
    # Open a local listener and probe it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.listen(1)
        assert lifecycle.is_proxy_listening(port=port, timeout=0.5) is True


@patch("harness.proxy.lifecycle.subprocess.Popen")
@patch("harness.proxy.lifecycle.is_proxy_listening")
def test_start_proxy_returns_none_when_already_listening(mock_listening, mock_popen) -> None:
    mock_listening.return_value = True
    proc = lifecycle.start_proxy()
    assert proc is None
    mock_popen.assert_not_called()


@patch("harness.proxy.lifecycle.subprocess.Popen")
@patch("harness.proxy.lifecycle.is_proxy_listening")
def test_start_proxy_polls_until_ready(mock_listening, mock_popen) -> None:
    # First call (in the "already listening?" check) returns False; subsequent
    # poll calls return True so start_proxy returns the Popen handle.
    mock_listening.side_effect = [False, True]
    mock_proc = MagicMock(pid=12345)
    mock_proc.poll.return_value = None
    mock_popen.return_value = mock_proc
    proc = lifecycle.start_proxy(wait_seconds=1.0)
    assert proc is mock_proc


@patch("harness.proxy.lifecycle.subprocess.Popen")
@patch("harness.proxy.lifecycle.is_proxy_listening")
def test_start_proxy_returns_none_when_child_dies(mock_listening, mock_popen) -> None:
    mock_listening.return_value = False
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # died
    mock_popen.return_value = mock_proc
    assert lifecycle.start_proxy(wait_seconds=1.0) is None


def test_stop_proxy_idempotent_on_none() -> None:
    lifecycle.stop_proxy(None)  # must not raise


def test_stop_proxy_terminates_and_waits() -> None:
    mock_proc = MagicMock()
    lifecycle.stop_proxy(mock_proc)
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
```

## Acceptance

- `python -m pytest tests/test_proxy_lifecycle.py` — all green.
- `python -m pytest --tb=short -q` — overall suite stays green.
- `harness coord run --help` shows the new `--proxy` flag.
- Manual: `harness coord run --spec spec/samples/hello-world.md --proxy auto`
  prints `proxy: started (pid=N)` and the run completes.

## Constraints

- Do NOT change any other test files; only add `tests/test_proxy_lifecycle.py`.
- Do NOT modify the proxy app itself (`src/harness/proxy/app.py`).
- Keep `lifecycle.py` under 80 LOC.
- Use stdlib only (socket, subprocess, time).  No new dependencies.

## Engine guidance

This is a single-file scope (the new lifecycle module) plus a surgical edit
to one location in cli.py.  Either `swarm/kimi` (agentic) or `swarm/kimi-api`
with FIND/REPLACE blocks works.  Timeout 420s should be plenty.
