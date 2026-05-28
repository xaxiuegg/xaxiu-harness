"""W14-HARNESS-SETUP 2026-05-26: interactive deploy wizard.

Single command that walks a non-technical operator from `git clone` to
first successful dispatch, with explicit consent at every step.

The wizard chains:

  1. Welcome banner + scope check
  2. Run `harness doctor` and surface results
  3. If any keys missing: offer to launch `harness keys serve` (browser
     form for paste + test + save)
  4. If `claude` CLI missing: explain how to install (don't auto-install
     because Claude Code is not pip-installable)
  5. If wrappers not installed (`claude-mimo` etc): offer to install
  6. Smoke test: dispatch a trivial prompt through the first configured
     engine to confirm everything wires up
  7. Print "what to do next" footer

Design principles
=================

  - **Consent-gated**: every action prompts; default is the safe choice.
  - **Idempotent**: safe to re-run.  Each step detects existing state +
    skips if already done.
  - **Non-interactive mode**: `--non-interactive` flag accepts all
    safe defaults (skip everything that would prompt; print what
    WOULD happen).  For CI / scripted bootstrap.
  - **No magic**: never modifies PATH, doesn't sudo, doesn't write
    outside the repo / ~/.harness dir.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _banner(line: str, color: str = "cyan") -> None:
    click.echo()
    click.echo(click.style("=" * 60, fg=color))
    click.echo(click.style(f"  {line}", fg=color, bold=True))
    click.echo(click.style("=" * 60, fg=color))


def _step(n: int, total: int, title: str) -> None:
    click.echo()
    click.echo(click.style(
        f"--- Step {n}/{total}: {title} ---",
        fg="yellow", bold=True,
    ))


def _ok(msg: str) -> None:
    click.echo(click.style(f"  ✓ {msg}", fg="green"))


def _warn(msg: str) -> None:
    click.echo(click.style(f"  ⚠ {msg}", fg="yellow"))


def _info(msg: str) -> None:
    click.echo(click.style(f"  • {msg}", fg="white"))


def _err(msg: str) -> None:
    click.echo(click.style(f"  ✗ {msg}", fg="red"))


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _step_doctor(non_interactive: bool) -> tuple[bool, dict]:
    """Run `harness doctor` and surface the results.

    Returns (any_issues, diagnoses_by_name).
    """
    from harness.doctor import run_all, overall_severity

    diagnoses = run_all()
    overall = overall_severity(diagnoses)
    by_name = {d.name: d for d in diagnoses}

    if overall == "ok":
        _ok("All 9 checks pass — no setup issues to fix")
        return False, by_name

    issues = [d for d in diagnoses if d.severity != "ok"]
    _warn(f"{len(issues)} of {len(diagnoses)} check(s) need attention:")
    for d in issues:
        glyph = "✗" if d.severity == "fail" else "⚠"
        color = "red" if d.severity == "fail" else "yellow"
        click.echo(
            click.style(f"    {glyph} {d.name}: {d.message}", fg=color)
        )
        if d.fix:
            click.echo(click.style(f"      fix: {d.fix}", fg="white", dim=True))
    return True, by_name


def _step_claude_binary(diag_by_name: dict, non_interactive: bool) -> None:
    """If claude CLI is missing, explain how to install.  We don't
    auto-install (Claude Code isn't pip-installable + it requires
    auth flow)."""
    cd = diag_by_name.get("claude_binary")
    if cd is None or cd.severity == "ok":
        return
    _warn("Claude Code CLI is not installed yet.")
    _info("Pattern B engines (kimi-via-claude, mimo-via-claude, "
          "deepseek-via-claude)")
    _info("AND the wrapper scripts (claude-mimo, etc.) require it.")
    _info("")
    _info("Install Claude Code from:")
    click.echo(click.style(
        "    https://docs.claude.com/en/docs/claude-code/setup",
        fg="cyan", underline=True,
    ))
    _info("")
    _info("Then verify with `claude --version` + come back here.")
    _info("(You can skip this step + come back to it later.)")
    if not non_interactive:
        click.pause("Press any key to continue (or Ctrl+C to exit "
                    "and install Claude Code now)...")


def _step_keys(diag_by_name: dict, non_interactive: bool) -> None:
    """If no API keys are configured, offer to launch the keys UI."""
    secrets_d = diag_by_name.get("secrets")
    if secrets_d is None or secrets_d.severity == "ok":
        _ok("API keys already configured — skipping keys UI")
        return

    _warn("No API keys configured.")
    _info("You can paste keys interactively via the browser-based UI:")
    _info("")
    _info("  python -m harness keys serve")
    _info("")
    _info("Opens 127.0.0.1:<random-port> with token-gated form.")
    _info("Save writes to .env (mode 0600 on POSIX, encrypted via")
    _info("DPAPI on Windows).")
    _info("")
    _info("Or edit .env directly (template is at .env.example).")

    if non_interactive:
        _info("(non-interactive mode: skipping launch)")
        return

    if click.confirm(
        "  → Launch the keys UI now?", default=True,
    ):
        from harness.keys_ui import serve_key_ui
        _info("Launching browser... (close the window or press Ctrl+C "
              "when done)")
        try:
            serve_key_ui(
                port=0,
                auto_open=True,
                idle_timeout_seconds=900.0,  # 15 min for setup
            )
        except KeyboardInterrupt:
            _info("Keys UI closed.")


def _step_wrappers(non_interactive: bool) -> None:
    """If the claude-* wrapper scripts aren't installed, offer to."""
    try:
        from harness.engines.wrapper_scripts import (
            DEFAULT_WRAPPER_DIR, list_wrappers,
        )
    except ImportError:
        _warn("Wrapper script module unavailable — skipping")
        return

    wrappers = list_wrappers()
    installed = sum(1 for w in wrappers if w["installed"])
    total = len(wrappers)
    if installed == total:
        _ok(f"All {total} wrapper scripts already installed at "
            f"{DEFAULT_WRAPPER_DIR}")
        return

    _warn(f"{installed}/{total} wrapper scripts installed.")
    _info(f"Wrappers live at {DEFAULT_WRAPPER_DIR}")
    _info("They let you run e.g. `claude-mimo 'your task'` to start "
          "a Claude Code")
    _info("session routed to MiMo (rather than Anthropic).")

    if non_interactive:
        _info("(non-interactive mode: skipping install)")
        return

    if click.confirm(
        "  → Install wrapper scripts now?", default=True,
    ):
        from harness.engines.wrapper_scripts import (
            get_path_hint, install_wrappers,
        )
        results = install_wrappers()
        for name, info in results.items():
            status = info.get("status", "?")
            if status == "installed":
                _ok(f"  installed {name}")
            elif status == "skipped-exists":
                _info(f"  {name} already exists — left alone")
            else:
                _warn(f"  {name}: {status}")
        hint = get_path_hint()
        if hint:
            _info("")
            _warn("Wrapper dir is not on your PATH yet.")
            click.echo("  " + hint.replace("\n", "\n  "))


def _step_agent_instructions(non_interactive: bool) -> None:
    """Install the user-level CLAUDE.md snippet so every future Claude
    Code session on this machine knows the harness is available.

    Idempotent — skips when already installed at the current version;
    offers to refresh when stale.  W14-SETUP-WIZARD-SNIPPET 2026-05-28
    (Phase 3.1 of agentic-operator roadmap).
    """
    try:
        from harness.introspect import _check_agent_instructions
        from harness import __version__ as live_v
    except Exception as e:
        _warn(f"Could not check snippet state: {e}")
        return

    ai = _check_agent_instructions()
    if ai["installed"] and ai["current"]:
        _ok(
            f"agent-instructions snippet already installed at "
            f"current version (v{ai.get('installed_version')})"
        )
        return

    if ai["installed"]:
        installed_v = ai.get("installed_version") or "<unversioned>"
        _warn(
            f"agent-instructions snippet is STALE "
            f"(installed v{installed_v}, current v{live_v})"
        )
    else:
        _warn(
            "agent-instructions snippet NOT installed."
        )
    _info(
        f"Target: {ai['target_path']}"
    )
    _info(
        "Every Claude Code session on this machine will read this "
        "snippet at startup, so it knows the harness is available + "
        "how to use it."
    )

    if non_interactive:
        _info("(non-interactive mode: skipping install)")
        return

    if click.confirm(
        "  → Install / refresh the snippet now?", default=True,
    ):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "harness",
             "install-agent-instructions", "--force"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                _info(line.strip())
        else:
            _warn(
                f"install-agent-instructions failed: "
                f"{result.stderr.strip()[:200]}"
            )


def _step_smoke_dispatch(
    diag_by_name: dict, non_interactive: bool,
) -> bool:
    """Run a minimal "say OK" dispatch through whichever Pattern B
    engine is configured to confirm end-to-end wiring."""
    # Skip if no claude binary
    cd = diag_by_name.get("claude_binary")
    if cd is not None and cd.severity != "ok":
        _info("Skipping smoke dispatch (claude binary not installed)")
        return False

    # Skip if no engine keys
    sd = diag_by_name.get("secrets")
    if sd is not None and sd.severity != "ok":
        _info("Skipping smoke dispatch (no API keys yet)")
        return False

    _info("Firing a 'say OK' dispatch through the first available "
          "Pattern B engine...")
    if non_interactive:
        _info("(non-interactive mode: skipping smoke dispatch — "
              "run `harness ask 'test'` manually to verify)")
        return False

    # Pick first configured engine
    for prefix, name in [
        ("MIMO_API_KEY", "mimo-via-claude"),
        ("DEEPSEEK_API_KEY", "deepseek-via-claude"),
        ("KIMI_API_KEY", "kimi-via-claude"),
    ]:
        if os.environ.get(prefix):
            break
    else:
        _info("No Pattern B-compatible key found — skipping smoke")
        return False

    try:
        from harness.engines.concrete import get_engine
        eng = get_engine(name)
        resp = eng.dispatch(
            "Reply with the single word OK.", "",
            {"max_budget_usd": 0.05, "timeout_s": 60},
        )
        if resp.success:
            _ok(f"Smoke dispatch via {name}: {resp.text.strip()[:80]} "
                f"({resp.cost_usd*1000:.1f} cents, "
                f"{resp.latency_ms / 1000:.1f}s)")
            return True
        else:
            _warn(f"Smoke dispatch via {name} failed: {resp.error[:200]}")
            return False
    except Exception as exc:
        _warn(f"Smoke dispatch raised: {type(exc).__name__}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_wizard(non_interactive: bool = False) -> int:
    """Run the interactive setup wizard.

    Returns process exit code: 0 on success, 1 if any required step
    failed.
    """
    _banner("xaxiu-harness setup wizard", color="cyan")
    click.echo(
        "  Guided walkthrough from blank machine to first dispatch.\n"
        "  Press Ctrl+C at any time to abort + return to your shell."
    )

    total_steps = 6
    issues: list[str] = []

    _step(1, total_steps, "Run preflight diagnostics (harness doctor)")
    any_issues, diag_by_name = _step_doctor(non_interactive)
    if any_issues:
        issues.append("doctor")

    _step(2, total_steps, "Claude Code CLI availability check")
    _step_claude_binary(diag_by_name, non_interactive)

    _step(3, total_steps, "API key configuration")
    _step_keys(diag_by_name, non_interactive)

    _step(4, total_steps, "Wrapper script installation")
    _step_wrappers(non_interactive)

    _step(5, total_steps, "Smoke dispatch")
    smoke_ok = _step_smoke_dispatch(diag_by_name, non_interactive)
    if not smoke_ok and not non_interactive:
        issues.append("smoke")

    _step(6, total_steps,
          "Install agent-instructions snippet (~/.claude/CLAUDE.md)")
    _step_agent_instructions(non_interactive)

    _banner("Setup wizard complete", color="green")
    click.echo()
    if not issues:
        _ok("Everything is set up.  Try:")
        click.echo()
        click.echo(click.style(
            "    harness ask 'your first question here'\n"
            "    harness engines list\n"
            "    harness keys list",
            fg="white",
        ))
    else:
        _warn(f"Setup finished with {len(issues)} open issue(s).")
        for i in issues:
            if i == "doctor":
                _info("Re-run `harness doctor` to see current state")
            elif i == "smoke":
                _info("Smoke dispatch didn't complete — try "
                      "`harness ask 'test'` to debug")
    click.echo()
    return 0 if not issues else 1
