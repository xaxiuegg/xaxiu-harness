"""W10-ENV-VAR-WIZARD: regression tests for `harness env-wizard`.

The wizard walks each required API key, prompts for missing ones,
stores via DPAPI, and probes to confirm.  Tests use Click's
CliRunner + stub the dpapi module + feed canned prompt inputs.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli


@pytest.fixture
def fake_dpapi(monkeypatch):
    """Replace dpapi with an in-memory dict-backed stub for tests."""
    store: dict[str, str] = {}

    def _has(name): return name in store
    def _encrypt(name, value): store[name] = value
    def _decrypt(name): return store.get(name)

    # Patch the module-level functions the wizard imports
    monkeypatch.setattr("harness.secrets.dpapi.has_secret", _has)
    monkeypatch.setattr("harness.secrets.dpapi.encrypt_secret", _encrypt)
    monkeypatch.setattr("harness.secrets.dpapi.decrypt_secret", _decrypt)
    # Also clear os.environ for the keys we care about
    for key, _ in _cli._ENV_WIZARD_KEYS:
        monkeypatch.delenv(key, raising=False)
    return store


# -- Non-interactive mode -------------------------------------------------


def test_wizard_non_interactive_no_prompts(fake_dpapi):
    """--non-interactive prints the plan + exits without prompting.

    Critical: no input collected; safe to invoke from CI/scripts."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard", "--non-interactive"])
    assert result.exit_code == 0
    # Each canonical key listed
    for key_name, _ in _cli._ENV_WIZARD_KEYS:
        assert key_name in result.output
    # All keys started missing, so wizard reports each as "would prompt"
    assert "would prompt" in result.output
    # No key written
    assert not fake_dpapi


def test_wizard_non_interactive_skips_set_keys_without_overwrite(fake_dpapi):
    """Already-set key skipped silently when --overwrite not passed."""
    fake_dpapi["KIMI_API_KEY"] = "existing-value"
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard", "--non-interactive"])
    assert result.exit_code == 0
    # KIMI shows as already set + skipping
    assert "[SET] KIMI_API_KEY" in result.output
    assert "already set, skipping" in result.output


def test_wizard_non_interactive_overwrite_prompts_set_keys(fake_dpapi):
    """--overwrite re-prompts even for set keys (in non-interactive mode,
    it says 'would prompt' instead of skipping)."""
    fake_dpapi["KIMI_API_KEY"] = "old-value"
    runner = CliRunner()
    result = runner.invoke(_cli.cli, [
        "env-wizard", "--non-interactive", "--overwrite",
    ])
    assert result.exit_code == 0
    # KIMI is set BUT wizard would still prompt because --overwrite
    kimi_section = result.output.split("[SET] KIMI_API_KEY")[1].split("\n[")[0]
    assert "would prompt" in kimi_section


# -- Interactive mode -----------------------------------------------------


def test_wizard_interactive_prompts_each_missing_key(fake_dpapi):
    """In interactive mode, each missing key gets a prompt.

    Feed canned inputs via CliRunner's input parameter.  One newline
    per key (5 keys total)."""
    # Provide a value for the first 2, skip the rest
    inputs = "kimi-real-key\ndeepseek-real-key\n\n\n\n"
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard"], input=inputs)
    assert result.exit_code == 0
    # Verify the first 2 are stored
    assert fake_dpapi.get("KIMI_API_KEY") == "kimi-real-key"
    assert fake_dpapi.get("DEEPSEEK_API_KEY") == "deepseek-real-key"
    # Remaining 3 skipped
    assert "MIMO_API_KEY" not in fake_dpapi
    assert "ANTHROPIC_API_KEY" not in fake_dpapi
    assert "GEMINI_API_KEY" not in fake_dpapi
    # Wizard reports the breakdown
    assert "2 newly stored" in result.output
    assert "3 skipped" in result.output


def test_wizard_interactive_empty_input_skips(fake_dpapi):
    """Empty input (just Enter) marks the key as skipped, doesn't store ''."""
    inputs = "\n\n\n\n\n"  # 5 keys, all skipped
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard"], input=inputs)
    assert result.exit_code == 0
    assert not fake_dpapi  # no keys written
    assert "5 skipped" in result.output


def test_wizard_interactive_skips_set_keys_by_default(fake_dpapi):
    """If a key is already in DPAPI, wizard doesn't re-prompt without --overwrite.

    With 1 key set, wizard prompts only the OTHER 4 — so we feed 4 inputs."""
    fake_dpapi["KIMI_API_KEY"] = "pre-existing"
    inputs = "\n\n\n\n"  # 4 inputs for the 4 missing keys
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard"], input=inputs)
    assert result.exit_code == 0
    # KIMI value untouched
    assert fake_dpapi["KIMI_API_KEY"] == "pre-existing"
    assert "1 already-set" in result.output


def test_wizard_interactive_overwrite_replaces_set_key(fake_dpapi):
    """--overwrite + interactive: paste a new value -> replaces old."""
    fake_dpapi["KIMI_API_KEY"] = "old-value"
    # 5 keys with --overwrite, all 5 prompted; provide new value for KIMI, skip rest
    inputs = "new-kimi-value\n\n\n\n\n"
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard", "--overwrite"],
                            input=inputs)
    assert result.exit_code == 0
    assert fake_dpapi["KIMI_API_KEY"] == "new-kimi-value"


def test_wizard_handles_dpapi_write_failure(fake_dpapi, monkeypatch):
    """If encrypt_secret raises, wizard exits 4 with a plain-language
    'what to do' hint."""
    def _boom(name, value):
        raise RuntimeError("DPAPI store unreadable")

    monkeypatch.setattr("harness.secrets.dpapi.encrypt_secret", _boom)
    inputs = "some-value\n"
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard"], input=inputs)
    assert result.exit_code == 4
    assert "failed to store key" in result.output.lower()
    # Operator gets actionable hint
    assert "DPAPI" in result.output


def test_wizard_explains_each_key_in_plain_language(fake_dpapi):
    """Operator sees a 1-line purpose for each key, not just the name."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard", "--non-interactive"])
    assert result.exit_code == 0
    # Spot-check 3 plain-language phrases
    assert "primary agentic engine" in result.output  # KIMI
    assert "V-file-spanning" in result.output         # DEEPSEEK
    assert "audit + brainstorm" in result.output      # MIMO


def test_wizard_help_text_mentions_dpapi():
    """--help surfaces that keys go into DPAPI so operators know
    they're secure-stored."""
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["env-wizard", "--help"])
    assert result.exit_code == 0
    assert "DPAPI" in result.output
