"""W11-HIDE-ADVANCED-VERBS: tests for the advanced/hidden verb split.

PATH-A item-4 shrink 2026-07-01: the engineering-tier verbs that used to
populate this file (spec-init, lint-spec, panic-dump, swarm-verify, burst,
lock, replay, ...) were DELETED outright, not just hidden.  What remains
statically hidden (decorator ``hidden=True``) is only ``engines-reliability``.
The runtime hiding of non-core verbs happens in ``main()`` via
``_hide_noncore_verbs()`` (not exercised by CliRunner, which invokes ``cli``
directly), so these tests check the static decorator contract + the
``advanced list`` browser.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from harness import cli as _cli


HIDDEN_VERBS = [
    "engines-reliability",
]


@pytest.mark.parametrize("verb_name", HIDDEN_VERBS)
def test_engineering_verb_marked_hidden(verb_name):
    """Each engineering verb has hidden=True so it's removed from --help."""
    cmd = _cli.cli.commands.get(verb_name)
    assert cmd is not None, f"verb {verb_name} not registered in cli"
    assert getattr(cmd, "hidden", False), (
        f"verb {verb_name} should be hidden=True (W11-HIDE-ADVANCED-VERBS)"
    )


def test_daily_use_verbs_NOT_hidden():
    """Operator-facing daily verbs must stay visible (static decorator check)."""
    visible_required = [
        "ask",
        "ask-history",
        "ask-show",
        "proxy",
        "keys",
        "env",
        "env-wizard",
        "doctor",
        "introspect",
        "engines",
        "engines-heal",
        "budget",
        "audit",
        "capabilities",
        "plan",
        "today",
        "session",
    ]
    for verb_name in visible_required:
        cmd = _cli.cli.commands.get(verb_name)
        assert cmd is not None, f"verb {verb_name} missing from cli"
        assert not getattr(cmd, "hidden", False), (
            f"verb {verb_name} should be visible (operator-facing)"
        )


@pytest.mark.parametrize("verb_name", HIDDEN_VERBS)
def test_hidden_verb_still_callable_via_help(verb_name):
    """Hidden=True hides from listing but doesn't break invocation."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [verb_name, "--help"])
    assert result.exit_code == 0, f"verb {verb_name} --help failed: {result.output[:200]}"
    assert verb_name in result.output or "Usage:" in result.output


def test_advanced_group_registered():
    assert "advanced" in _cli.cli.commands
    assert isinstance(_cli.cli.commands["advanced"], type(_cli.cli))  # ClickGroup


def test_advanced_list_subcommand_works():
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "list"])
    assert result.exit_code == 0
    found = sum(1 for v in HIDDEN_VERBS if v in result.output)
    assert found >= 1, (
        f"advanced list output missing hidden verbs; found {found} in: {result.output[:500]}"
    )


def test_advanced_list_explains_invocation():
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "list"])
    assert "Invoke" in result.output or "harness <verb>" in result.output


def test_advanced_help_shows_list_subcommand():
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output


def test_default_help_omits_hidden_verbs():
    """`harness --help` must NOT show statically-hidden verbs."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["--help"])
    assert result.exit_code == 0
    for verb_name in HIDDEN_VERBS:
        indented = f"\n  {verb_name}"
        assert indented not in result.output, f"hidden verb {verb_name} appears in --help"
