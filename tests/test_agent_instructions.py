"""W14-AGENT-INSTRUCTIONS 2026-05-26: tests for the agent-instructions
CLI verb that emits a snippet teaching new agent sessions about the
harness."""
from __future__ import annotations

from click.testing import CliRunner

from harness.cli import cli


class TestAgentInstructionsCli:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["agent-instructions", "--help"])
        assert result.exit_code == 0
        assert "snippet" in result.output.lower()

    def test_claude_md_format_default(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["agent-instructions"])
        assert result.exit_code == 0
        # H2 header for the CLAUDE.md section
        assert "## xaxiu-harness is available" in result.output
        # Lists the key verbs
        assert "harness ask" in result.output
        assert "harness doctor" in result.output
        assert "harness engines recommend" in result.output
        assert "harness keys serve" in result.output
        # Documents the cost + time
        assert "0.20-0.30" in result.output or "$0.20" in result.output
        # Mentions the output dir convention
        assert "packet.md" in result.output

    def test_short_format(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["agent-instructions", "--format", "short"],
        )
        assert result.exit_code == 0
        # Single paragraph, no headers
        assert "## " not in result.output
        # Still mentions the key verb
        assert "harness ask" in result.output

    def test_prompt_format(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["agent-instructions", "--format", "prompt"],
        )
        assert result.exit_code == 0
        # Has the "you have xaxiu-harness" framing
        assert "harness" in result.output.lower()
        # Mentions where outputs land
        assert "packet.md" in result.output

    def test_bakes_in_absolute_install_path(self) -> None:
        """The snippet should include the absolute path to the
        harness install (not a placeholder) so the agent knows
        exactly where the install lives."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["agent-instructions", "--format", "short"],
        )
        assert result.exit_code == 0
        # The path should contain "harness" — actual install location
        # is machine-specific but should never be a placeholder
        assert "<install-path>" not in result.output
        assert "${HARNESS_PATH}" not in result.output
        # The path should be there (matches the install dir)
        # We can't check the exact path because it varies per machine,
        # but it should look path-like (contain a directory separator)
        assert "/" in result.output or "\\" in result.output

    def test_invalid_format_rejected(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["agent-instructions", "--format", "garbage"],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# install-agent-instructions
# ---------------------------------------------------------------------------


class TestInstallAgentInstructions:
    def _run(self, runner, *args, target: Path):
        return runner.invoke(
            cli, ["install-agent-instructions", "--target", str(target)] + list(args),
        )

    def test_dry_run_does_not_write(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        result = self._run(runner, "--dry-run", target=target)
        assert result.exit_code == 0
        assert not target.exists()
        # Preview should appear in output
        assert "Would append" in result.output
        assert "harness ask" in result.output

    def test_append_creates_file_if_missing(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "subdir" / "claude.md"  # parent doesn't exist
        result = self._run(runner, target=target)
        assert result.exit_code == 0
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "W14-HARNESS-AGENT-INSTRUCTIONS-START" in content
        assert "W14-HARNESS-AGENT-INSTRUCTIONS-END" in content
        assert "harness ask" in content

    def test_append_preserves_existing_content(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        target.write_text(
            "# My personal Claude config\n\n"
            "Some existing notes I have.\n",
            encoding="utf-8",
        )
        result = self._run(runner, target=target)
        assert result.exit_code == 0
        content = target.read_text(encoding="utf-8")
        assert "My personal Claude config" in content
        assert "Some existing notes I have" in content
        assert "W14-HARNESS-AGENT-INSTRUCTIONS-START" in content

    def test_idempotent_second_run_does_not_duplicate(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        self._run(runner, target=target)
        size_after_first = target.stat().st_size
        # Run again — should be a no-op
        result = self._run(runner, target=target)
        assert result.exit_code == 0
        assert "already present" in result.output.lower()
        assert target.stat().st_size == size_after_first

    def test_force_replaces_existing_block(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        self._run(runner, target=target)
        # Manually corrupt the block
        content = target.read_text(encoding="utf-8")
        content = content.replace("harness ask", "MARKER_THAT_WILL_BE_REPLACED")
        target.write_text(content, encoding="utf-8")
        # Force re-install — should rewrite the block
        result = self._run(runner, "--force", target=target)
        assert result.exit_code == 0
        new_content = target.read_text(encoding="utf-8")
        # Corrupted marker should be gone; canonical content restored
        assert "MARKER_THAT_WILL_BE_REPLACED" not in new_content
        assert "harness ask" in new_content

    def test_uninstall_removes_block_preserves_rest(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        target.write_text(
            "# Personal notes\n\nKeep this content.\n",
            encoding="utf-8",
        )
        # Install
        self._run(runner, target=target)
        assert "W14-HARNESS" in target.read_text(encoding="utf-8")
        # Uninstall
        result = self._run(runner, "--uninstall", target=target)
        assert result.exit_code == 0
        content = target.read_text(encoding="utf-8")
        assert "Personal notes" in content  # preserved
        assert "Keep this content" in content  # preserved
        assert "W14-HARNESS" not in content  # block removed

    def test_uninstall_no_block_is_noop(self, tmp_path) -> None:
        runner = CliRunner()
        target = tmp_path / "claude.md"
        target.write_text("just my personal stuff\n", encoding="utf-8")
        result = self._run(runner, "--uninstall", target=target)
        assert result.exit_code == 0
        assert "no harness section found" in result.output.lower()
        # File untouched
        assert (
            target.read_text(encoding="utf-8") == "just my personal stuff\n"
        )

    def test_install_default_target_is_user_claude_md(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        # Redirect HOME so we don't actually write the operator's CLAUDE.md
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
        runner = CliRunner()
        # No --target — uses default ~/.claude/CLAUDE.md
        result = runner.invoke(cli, ["install-agent-instructions", "--dry-run"])
        assert result.exit_code == 0
        # Should reference the .claude path in the dry-run preview
        assert ".claude" in result.output or "CLAUDE.md" in result.output

    def test_install_uses_current_template(self, tmp_path: Path) -> None:
        """W14-ASK-DOCS regression: prior to the helper refactor,
        install-agent-instructions carried its OWN inline snippet that
        drifted from `harness agent-instructions` output.  Both commands
        must now route through `_agent_instructions_snippet` so they
        cannot disagree.

        Fingerprints: the v0.5.1+ template covers --audit + --panel +
        the proxy + xaxiu-swarm.  None of those existed in the stale
        pre-v0.5.1 template.  Their presence here proves install is
        using the current shared source.
        """
        target = tmp_path / "claude.md"
        target.write_text("# placeholder\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "install-agent-instructions", "--target", str(target),
            "--force", "--dry-run",
        ])
        assert result.exit_code == 0
        out = result.output
        # Positive: new-template fingerprints
        assert "--audit" in out
        assert "--panel" in out
        assert "harness proxy" in out
        assert "xaxiu-swarm" in out
        # Negative: stale-template fingerprint absent
        assert "fires 3 engines (Kimi / MiMo / DeepSeek)" not in out

    def test_install_and_print_emit_same_claude_md_snippet(
        self, tmp_path: Path,
    ) -> None:
        """Regression: extract the snippet from install --dry-run's
        wrapped output and confirm it matches `agent-instructions`
        verbatim.  Single source of truth via the helper function."""
        runner = CliRunner()
        # Print path
        print_result = runner.invoke(cli, ["agent-instructions"])
        assert print_result.exit_code == 0
        printed = print_result.output

        # Install --dry-run --force path
        target = tmp_path / "claude.md"
        target.write_text("# placeholder\n", encoding="utf-8")
        install_result = runner.invoke(cli, [
            "install-agent-instructions", "--target", str(target),
            "--force", "--dry-run",
        ])
        assert install_result.exit_code == 0
        # Every paragraph of the printed snippet should appear in
        # install's preview.  We don't require byte-equality (install
        # wraps with markers + adds a "Would replace in:" header)
        # but every line of substance must be present.
        for line in printed.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                # Skip blank lines / markdown headers (whitespace-
                # sensitive comparison would be too brittle)
                continue
            if len(line) < 20:
                # Skip very short lines (code fences, etc.) to keep
                # the assertion focused on meaningful content
                continue
            assert line in install_result.output, (
                f"Install preview missing printed line: {line!r}"
            )
