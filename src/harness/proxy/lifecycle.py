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
    # Best-effort: this site catches errors from a telemetry / cleanup / log path and intentionally swallows them to keep the primary operation resilient.
    except Exception:
        pass
