"""W11-HIDE-ADVANCED-VERBS: tests for the advanced/hidden verb split.

12 engineering verbs are hidden from the default `harness --help`:
spec-register, spec-verify, spec-init, lint-spec, panic-dump,
swarm-verify, engines-reliability, engines-cooldowns, burst, lock,
replay, proxy (group).

They remain CALLABLE (hidden=True only affects help discovery).
`harness advanced list` enumerates them for operators who need to
find them.

Audit follow-through 2026-05-27 (W14-COORD-UNHIDE): ``coord`` was
previously in this list because v2 was treated as experimental
scaffolding.  Now that ``coord`` is documented as a first-class
operating mode in docs/OPERATOR_GUIDE.md § 3.3 and
docs/AGENT_REFERENCE.md § 10, it must appear in ``harness --help``
to match the docs.  Test moved to ``test_visible_daily_use_verbs``.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from harness import cli as _cli


HIDDEN_VERBS = [
    # PATH-A-TRIM 2026-05-29: spec-register / spec-verify / engines-cooldowns
    # removed with the coord/loops machinery they depended on.
    "spec-init",
    "lint-spec",
    "panic-dump",
    "swarm-verify",
    "engines-reliability",
    "burst",
    "lock",
    "replay",
    # NOTE: ``proxy`` was previously hidden (W11-HIDE-ADVANCED-VERBS) but
    # was unhidden 2026-05-28 (W14-PROXY-UNHIDE) after a fresh-session
    # sub-agent test surfaced that a hidden top-level verb causes agents
    # to conclude "no proxy verb exists" when they verify via --help,
    # even when the agent-instructions snippet documents the verb.  The
    # same operational bug as W14-COORD-UNHIDE.
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
    """Operator-facing daily verbs must stay visible.

    Audit follow-through 2026-05-27: ``coord`` added to this list when
    it was unhidden (was in HIDDEN_VERBS pre-W14-COORD-UNHIDE).
    """
    visible_required = [
        "daily",
        "today",
        "morning-brief",
        "preflight",
        "dispatch",
        "env",
        "env-wizard",
        "profile",
        "status",
        "doctor",
        "engines-heal",
        "session",
        "budget",
        "adapter",
        "queue",
        "memory",
        # PATH-A-TRIM 2026-05-29: observer / loop / dashboard-serve / coord
        # removed with their machinery; dropped from the visible-required list.
        "proxy",  # W14-PROXY-UNHIDE 2026-05-28 (sub-agent test feedback)
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
    assert result.exit_code == 0, f"verb {verb_name} --help failed: {result.output[:200]}"
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
        # Short-name verbs could collide with prose mentioning them
        # (low risk but pedantic).  Test those strict; long-name verbs
        # by indented-line presence.
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
            assert indented not in result.output, f"hidden verb {verb_name} appears in --help"
