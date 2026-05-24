"""W11-HIDE-ADVANCED-VERBS: tests for the advanced/hidden verb split.

13 engineering verbs are hidden from the default `harness --help`:
spec-register, spec-verify, spec-init, lint-spec, panic-dump,
swarm-verify, engines-reliability, engines-cooldowns, burst, lock,
replay, proxy (group), coord (group).

They remain CALLABLE (hidden=True only affects help discovery).
`harness advanced list` enumerates them for operators who need to
find them.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from harness import cli as _cli


HIDDEN_VERBS = [
    "spec-register",
    "spec-verify",
    "spec-init",
    "lint-spec",
    "panic-dump",
    "swarm-verify",
    "engines-reliability",
    "engines-cooldowns",
    "burst",
    "lock",
    "replay",
    "proxy",
    "coord",
]


# -- Hidden flag set correctly --------------------------------------------


@pytest.mark.parametrize("verb_name", HIDDEN_VERBS)
def test_engineering_verb_marked_hidden(verb_name):
    """Each engineering verb has hidden=True so it's removed from --help."""
    cmd = _cli.cli.commands.get(verb_name)
    assert cmd is not None, f"verb {verb_name} not registered in cli"
    assert getattr(cmd, "hidden", False), (
        f"verb {verb_name} should be hidden=True (W11-HIDE-ADVANCED-VERBS)"
    )


def test_daily_use_verbs_NOT_hidden():
    """Operator-facing daily verbs must stay visible."""
    visible_required = [
        "daily", "today", "morning-brief", "preflight", "dispatch",
        "env", "env-wizard", "profile", "status", "doctor",
        "engines-heal", "session", "budget", "observer", "loop",
        "adapter", "queue", "memory", "dashboard-serve",
    ]
    for verb_name in visible_required:
        cmd = _cli.cli.commands.get(verb_name)
        assert cmd is not None, f"verb {verb_name} missing from cli"
        assert not getattr(cmd, "hidden", False), (
            f"verb {verb_name} should be visible (operator-facing)"
        )


# -- Hidden verbs still callable -----------------------------------------


@pytest.mark.parametrize("verb_name", HIDDEN_VERBS)
def test_hidden_verb_still_callable_via_help(verb_name):
    """Hidden=True hides from listing but doesn't break invocation.

    Calling `harness <verb> --help` must still produce help output for
    the verb itself (proves the command is registered + reachable)."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [verb_name, "--help"])
    assert result.exit_code == 0, (
        f"verb {verb_name} --help failed: {result.output[:200]}"
    )
    # Help output should mention the verb name OR the docstring
    assert verb_name in result.output or "Usage:" in result.output


# -- `harness advanced` group --------------------------------------------


def test_advanced_group_registered():
    assert "advanced" in _cli.cli.commands
    assert isinstance(_cli.cli.commands["advanced"], type(_cli.cli))  # ClickGroup


def test_advanced_list_subcommand_works():
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "list"])
    assert result.exit_code == 0
    # Output should include at least 5 of the hidden verbs by name
    found = sum(1 for v in HIDDEN_VERBS if v in result.output)
    assert found >= 5, (
        f"advanced list output missing many hidden verbs; found {found}/13 "
        f"in: {result.output[:500]}"
    )


def test_advanced_list_explains_invocation():
    """The list output must tell the operator how to actually call the
    hidden verbs (otherwise it's just a confusing catalog)."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "list"])
    assert "Invoke" in result.output or "harness <verb>" in result.output


def test_advanced_help_shows_list_subcommand():
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["advanced", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output


# -- Default --help omits hidden verbs -----------------------------------


def test_default_help_omits_hidden_verbs():
    """The operator's daily `harness --help` must NOT show the 13 hidden
    verbs in the Commands listing (Click's hidden=True contract)."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["--help"])
    assert result.exit_code == 0
    # Each hidden verb should NOT appear as a line item in the help.
    # Click's --help puts each verb on its own line indented; check the
    # verb does NOT start a line (with optional leading whitespace).
    import re
    for verb_name in HIDDEN_VERBS:
        # Skip "proxy" + "coord" because they could collide with descriptive
        # text mentioning them (low risk but pedantic).  Test the strict
        # ones explicitly.
        if verb_name in ("burst", "lock", "replay"):
            # These short names could conflict with prose; check explicitly
            pattern = rf"^\s{{2,4}}{re.escape(verb_name)}\s"
            assert not re.search(pattern, result.output, re.MULTILINE), (
                f"hidden verb {verb_name} appears in --help"
            )
        else:
            # Long-name verbs: just check they're not in the verb listing
            # by looking for the indented prefix
            indented = f"\n  {verb_name}"
            assert indented not in result.output, (
                f"hidden verb {verb_name} appears in --help"
            )
