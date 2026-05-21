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
