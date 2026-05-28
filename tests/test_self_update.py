"""W14-SELF-UPDATE 2026-05-28: tests for `harness self-update` (Phase
3.2 of agentic-operator roadmap)."""
from __future__ import annotations

from click.testing import CliRunner

from harness.cli import cli


class TestSelfUpdateCli:
    def test_help_describes_three_steps(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["self-update", "--help"])
        assert result.exit_code == 0
        # Help must mention all three things the verb does
        assert "git pull" in result.output or "pull" in result.output.lower()
        assert "pip install" in result.output or "install" in result.output
        assert "snippet" in result.output.lower() or \
               "install-agent-instructions" in result.output

    def test_dry_run_does_not_modify(self) -> None:
        """--dry-run + all skip flags should print headers without
        running anything."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "self-update", "--dry-run",
            "--no-pull", "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()
        # All three sections present as SKIPPED
        assert "SKIPPED" in result.output

    def test_dry_run_with_pull_shows_what_would_happen(self) -> None:
        """--dry-run should show whether the repo is behind upstream
        WITHOUT actually pulling."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "self-update", "--dry-run", "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        # Either "Would pull", "Already up to date", or "uncommitted changes"
        out = result.output.lower()
        assert any(s in out for s in [
            "would pull", "already up to date", "uncommitted",
            "not a git repo",
        ])

    def test_no_pull_skips_pull_step(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "self-update", "--dry-run", "--no-pull",
            "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        # Pull section shows SKIPPED
        assert "SKIPPED (--no-pull)" in result.output

    def test_no_install_skips_pip(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "self-update", "--dry-run", "--no-pull",
            "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        assert "SKIPPED (--no-install)" in result.output

    def test_no_snippet_skips_install_agent_instructions(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "self-update", "--dry-run", "--no-pull",
            "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        assert "SKIPPED (--no-snippet)" in result.output

    def test_reports_live_version(self) -> None:
        """Banner must surface the live harness version."""
        runner = CliRunner()
        from harness import __version__ as _v
        result = runner.invoke(cli, [
            "self-update", "--dry-run", "--no-pull",
            "--no-install", "--no-snippet",
        ])
        assert result.exit_code == 0
        assert _v in result.output
