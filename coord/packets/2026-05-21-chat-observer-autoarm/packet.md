# CHAT-OBSERVER-AUTO-ARM — register chat audit on cadence

## Goal

`harness observer install-scheduler` already registers the v1 observer
cycle via Windows Task Scheduler.  Add a sibling task for the new
chat observer (CHAT-OBSERVER landed earlier this session).

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. Extend `src/harness/observer/scheduler.py`

Locate the function that registers the observer task (search for
`Register-ScheduledTask` or `register_tasks`).  Add a second registration
for the chat audit, controlled by a new optional parameter.

```python
def register_chat_audit_task(
    cadence_minutes: int = 60,
    task_prefix: str = TASK_NAME_PREFIX,
) -> bool:
    """Register the chat-observer audit task in Windows Task Scheduler."""
    # Uses the same pattern as the existing observer cycle registration:
    # PowerShell Register-ScheduledTask with cron-equivalent trigger,
    # action = `python -m harness observer audit-chat`.
    ...
```

If `register_tasks` is the public entry point, accept an
`include_chat: bool = False` kwarg and call the helper when set.

### 2. CLI flag on `observer install-scheduler`

Find the existing `@observer.command(name="install-scheduler")` in
`src/harness/cli.py` (around line 800-820).  Add a new option:

```python
@click.option("--include-chat", is_flag=True,
              help="Also register the chat-observer audit task (CHAT-OBSERVER).")
```

Pass it to the underlying registration call.

### 3. Tests

New file `tests/test_observer_chat_autoarm.py`:

```python
"""Tests for CHAT-OBSERVER-AUTO-ARM registration."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_register_chat_audit_task_returns_true_on_success() -> None:
    """register_chat_audit_task invokes PowerShell + returns True on rc=0."""
    from harness.observer import scheduler

    with patch.object(scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok = scheduler.register_chat_audit_task(cadence_minutes=30)
        assert ok is True
        called = mock_sub.run.call_args
        # The PS command should mention "audit-chat" so we know it's the right task
        cmd_str = " ".join(str(x) for x in called[0][0])
        assert "audit-chat" in cmd_str


def test_register_chat_audit_task_returns_false_on_failure() -> None:
    from harness.observer import scheduler
    with patch.object(scheduler, "subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=1, stdout="", stderr="ACCESS DENIED")
        ok = scheduler.register_chat_audit_task()
        assert ok is False


def test_cli_observer_install_scheduler_include_chat_flag() -> None:
    """`harness observer install-scheduler --include-chat` triggers chat task registration."""
    from click.testing import CliRunner
    from harness.cli import cli
    with patch("harness.observer.scheduler.register_tasks") as mock_reg, \
         patch("harness.observer.scheduler.register_chat_audit_task") as mock_chat:
        mock_reg.return_value = True
        mock_chat.return_value = True
        runner = CliRunner()
        result = runner.invoke(cli, ["observer", "install-scheduler", "--include-chat"])
    assert result.exit_code == 0, result.output
    mock_chat.assert_called_once()
```

## Acceptance

- `python -m pytest tests/test_observer_chat_autoarm.py` — green.
- Full suite still green.
- `harness observer install-scheduler --help` shows `--include-chat`.

## Constraints

- DO NOT touch the existing observer cycle registration.
- Stdlib only.
- Keep new function under 60 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
