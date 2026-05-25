"""W13-HARNESS-PLAN-VERB: tests for the plan loader + CLI surface.

`harness plan show` is the orientation verb that lets a fresh agent
read the active strategic plan without grepping the repo.  It also
closes a hallucination gap: future "what should I be doing right now"
prompts can be answered from a single canonical document rather than
the agent guessing from STATUS.csv / commit messages / chat history.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# harness.plan module
# ---------------------------------------------------------------------------


class TestPlanPath:
    def test_default_path_lives_under_repo_root(self):
        from harness.plan import plan_path, DEFAULT_PLAN_RELPATH
        p = plan_path()
        assert p.name == "CURRENT_PLAN.md"
        # Path should end in coord/CURRENT_PLAN.md
        assert str(p).endswith(str(DEFAULT_PLAN_RELPATH).replace("\\", "/")) \
            or str(p).endswith(str(DEFAULT_PLAN_RELPATH))

    def test_override_argument_wins(self, tmp_path):
        from harness.plan import plan_path
        override = tmp_path / "my-plan.md"
        assert plan_path(override).resolve() == override.resolve()

    def test_env_var_wins_when_no_override(self, tmp_path, monkeypatch):
        from harness.plan import plan_path
        target = tmp_path / "env-plan.md"
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(target))
        assert plan_path().resolve() == target.resolve()

    def test_explicit_override_beats_env(self, tmp_path, monkeypatch):
        from harness.plan import plan_path
        monkeypatch.setenv("HARNESS_PLAN_PATH",
                            str(tmp_path / "env-plan.md"))
        explicit = tmp_path / "explicit-plan.md"
        assert plan_path(explicit).resolve() == explicit.resolve()


class TestLoadCurrentPlan:
    def test_missing_file_returns_exists_false_not_raises(self, tmp_path):
        from harness.plan import load_current_plan
        info = load_current_plan(tmp_path / "does-not-exist.md")
        assert info["exists"] is False
        assert info["body"] == ""
        assert info["body_chars"] == 0
        assert info["last_modified_iso"] is None

    def test_existing_file_returns_body(self, tmp_path):
        from harness.plan import load_current_plan
        p = tmp_path / "plan.md"
        body = "# A plan\n\nbody text\n"
        p.write_text(body, encoding="utf-8")
        info = load_current_plan(p)
        assert info["exists"] is True
        assert info["body"] == body
        assert info["body_chars"] == len(body)
        assert info["last_modified_iso"] is not None
        # mtime ISO format sanity check
        assert "T" in info["last_modified_iso"]

    def test_unicode_body_preserved(self, tmp_path):
        from harness.plan import load_current_plan
        p = tmp_path / "plan.md"
        # Non-ASCII content
        body = "# Plan with unicode\n\n* item with arrow ->\n"
        p.write_text(body, encoding="utf-8")
        info = load_current_plan(p)
        assert info["body"] == body

    def test_env_override_works_end_to_end(self, tmp_path, monkeypatch):
        from harness.plan import load_current_plan
        p = tmp_path / "env-plan.md"
        p.write_text("# via env\n", encoding="utf-8")
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(p))
        info = load_current_plan()  # no arg — picks up env
        assert info["exists"] is True
        assert "via env" in info["body"]


class TestCurrentPlanFileShipped:
    """Lightweight contract checks on the actual shipped plan file."""

    def test_current_plan_md_exists_in_repo(self):
        from harness.plan import plan_path
        p = plan_path()
        assert p.is_file(), (
            f"coord/CURRENT_PLAN.md is missing at {p} — this file is "
            f"load-bearing for `harness plan show` + the AGENT_QUICKSTART "
            f"hallucination-resistance checklist (section 12)."
        )

    def test_current_plan_md_has_required_sections(self):
        from harness.plan import load_current_plan
        info = load_current_plan()
        assert info["exists"]
        body = info["body"]
        # Section headers the file MUST keep (so fresh agents always
        # find the same orientation landmarks)
        for marker in (
            "## North star",
            "## Where we are right now",
            "## What's next",
            "## Single most important action",
            "## How to update this file",
        ):
            assert marker in body, (
                f"coord/CURRENT_PLAN.md missing required section: {marker!r}"
            )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestPlanCLI:
    def test_plan_group_registered(self):
        from harness.cli import cli
        assert "plan" in cli.commands

    def test_plan_show_help_works(self):
        from click.testing import CliRunner
        from harness.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output.lower()

    def test_plan_show_renders_pretty_with_header(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from harness.cli import cli
        p = tmp_path / "plan.md"
        p.write_text("# Plan body\n", encoding="utf-8")
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(p))
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show"])
        assert result.exit_code == 0
        assert "Current strategic plan" in result.output
        assert "Plan body" in result.output

    def test_plan_show_raw_skips_header(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from harness.cli import cli
        p = tmp_path / "plan.md"
        p.write_text("# Plan body\nline 2\n", encoding="utf-8")
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(p))
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show", "--format", "raw"])
        assert result.exit_code == 0
        assert "Plan body" in result.output
        assert "Current strategic plan" not in result.output

    def test_plan_show_json_emits_parseable_dict(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from harness.cli import cli
        p = tmp_path / "plan.md"
        p.write_text("# JSON plan\n", encoding="utf-8")
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(p))
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show", "--format", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["exists"] is True
        assert "JSON plan" in parsed["body"]
        assert parsed["body_chars"] == len("# JSON plan\n")

    def test_plan_show_missing_file_exits_nonzero(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from harness.cli import cli
        monkeypatch.setenv("HARNESS_PLAN_PATH",
                            str(tmp_path / "nope.md"))
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "show"])
        assert result.exit_code != 0
        # Error message should be helpful, not a traceback
        assert "no plan found" in (result.output + result.stderr).lower() \
            or "No plan found" in (result.output + (result.stderr or ""))

    def test_plan_path_prints_absolute_path(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from harness.cli import cli
        target = tmp_path / "abs-plan.md"
        monkeypatch.setenv("HARNESS_PLAN_PATH", str(target))
        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "path"])
        assert result.exit_code == 0
        assert str(target.resolve()) in result.output \
            or str(target) in result.output


# ---------------------------------------------------------------------------
# `harness capabilities` surfaces the plan (lightweight discoverability)
# ---------------------------------------------------------------------------


def test_capabilities_does_not_break_with_plan_module_loaded():
    """Sanity: importing the plan module + calling capabilities() must
    not regress.  Catches accidental circular-import bugs."""
    from harness import capabilities
    cap = capabilities()
    assert "plan" in cap["cli_verbs"]
