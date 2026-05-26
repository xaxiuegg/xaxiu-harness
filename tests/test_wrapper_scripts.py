"""W14-CLAUDE-CODE-WRAPPER-SCRIPTS: tests for the wrapper generator.

Coverage:
  - Each WRAPPER_DEFINITION resolves to a valid endpoint + model
  - POSIX template renders correctly + is executable on install
  - Windows template renders correctly with .cmd suffix
  - install_wrappers writes files + sets +x bit on POSIX
  - install_wrappers with only=[...] honors the subset
  - install_wrappers with overwrite=False preserves existing files
  - install_wrappers handles unknown wrapper names gracefully
  - list_wrappers reports correct installed + key_present state
  - get_path_hint returns None when dir is on PATH, hint otherwise
  - Wrappers contain NO secret values (only env-var references)
  - CLI: harness engines install-wrappers + list-wrappers
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.engines.wrapper_scripts import (
    DEFAULT_WRAPPER_DIR,
    POSIX_WRAPPER_TEMPLATE,
    WINDOWS_WRAPPER_TEMPLATE,
    WRAPPER_DEFAULT_MODELS,
    WRAPPER_DEFINITIONS,
    WRAPPER_PROVIDER_ENDPOINTS,
    _is_windows,
    _render_wrapper,
    get_path_hint,
    install_wrappers,
    list_wrappers,
)


# ---------------------------------------------------------------------------
# Wrapper definition integrity
# ---------------------------------------------------------------------------


class TestWrapperDefinitions:
    def test_every_definition_has_required_keys(self) -> None:
        for name, spec in WRAPPER_DEFINITIONS.items():
            assert "engine_key" in spec, f"{name} missing engine_key"
            assert "key_env" in spec, f"{name} missing key_env"
            assert "description" in spec, f"{name} missing description"

    def test_engine_keys_resolve_to_endpoint(self) -> None:
        for name, spec in WRAPPER_DEFINITIONS.items():
            engine_key = spec["engine_key"]
            assert engine_key in WRAPPER_PROVIDER_ENDPOINTS, (
                f"{name}: engine_key={engine_key!r} not in "
                f"WRAPPER_PROVIDER_ENDPOINTS"
            )
            endpoint = WRAPPER_PROVIDER_ENDPOINTS[engine_key]
            assert endpoint.startswith("https://"), (
                f"{name}: endpoint must be https URL, got {endpoint!r}"
            )

    def test_engine_keys_resolve_to_default_model(self) -> None:
        for name, spec in WRAPPER_DEFINITIONS.items():
            engine_key = spec["engine_key"]
            assert engine_key in WRAPPER_DEFAULT_MODELS, (
                f"{name}: engine_key={engine_key!r} not in "
                f"WRAPPER_DEFAULT_MODELS"
            )
            model = WRAPPER_DEFAULT_MODELS[engine_key]
            assert model, f"{name}: default_model is empty"

    def test_known_providers_have_wrappers(self) -> None:
        """All 5 major providers researched in FINDINGS.md have a wrapper."""
        expected = {"claude-mimo", "claude-mimo-payg", "claude-kimi",
                    "claude-deepseek", "claude-glm", "claude-qwen"}
        assert expected <= set(WRAPPER_DEFINITIONS.keys())


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRenderWrapper:
    def test_posix_render_for_mimo(self) -> None:
        spec = WRAPPER_DEFINITIONS["claude-mimo"]
        filename, contents = _render_wrapper(
            "claude-mimo", spec, use_windows=False,
        )
        assert filename == "claude-mimo"  # no .sh suffix
        assert contents.startswith("#!/bin/bash")
        assert "ANTHROPIC_BASE_URL" in contents
        assert "ANTHROPIC_AUTH_TOKEN" in contents
        assert "ANTHROPIC_MODEL" in contents
        # Refers to env-var name, NOT a hardcoded secret
        assert "${MIMO_API_KEY}" in contents

    def test_windows_render_for_mimo(self) -> None:
        spec = WRAPPER_DEFINITIONS["claude-mimo"]
        filename, contents = _render_wrapper(
            "claude-mimo", spec, use_windows=True,
        )
        assert filename == "claude-mimo.cmd"
        assert contents.startswith("@echo off")
        # Refers to env-var name via Windows %VAR% syntax
        assert "%MIMO_API_KEY%" in contents
        assert "ANTHROPIC_BASE_URL=" in contents

    def test_posix_has_existence_check(self) -> None:
        """The POSIX wrapper refuses if key env-var is empty."""
        spec = WRAPPER_DEFINITIONS["claude-kimi"]
        _, contents = _render_wrapper(
            "claude-kimi", spec, use_windows=False,
        )
        # Check the env var presence test
        assert 'if [ -z "${KIMI_API_KEY}" ]; then' in contents
        assert "exit 64" in contents

    def test_windows_has_existence_check(self) -> None:
        spec = WRAPPER_DEFINITIONS["claude-deepseek"]
        _, contents = _render_wrapper(
            "claude-deepseek", spec, use_windows=True,
        )
        assert 'if "%DEEPSEEK_API_KEY%"==""' in contents
        assert "exit /b 64" in contents

    def test_endpoint_url_in_rendered(self) -> None:
        spec = WRAPPER_DEFINITIONS["claude-deepseek"]
        _, contents = _render_wrapper(
            "claude-deepseek", spec, use_windows=False,
        )
        assert "https://api.deepseek.com/anthropic" in contents

    def test_default_model_in_rendered(self) -> None:
        spec = WRAPPER_DEFINITIONS["claude-mimo"]
        _, contents = _render_wrapper(
            "claude-mimo", spec, use_windows=False,
        )
        assert "mimo-v2.5-pro" in contents


class TestSecretSafety:
    """Wrappers MUST NOT contain hardcoded secrets — only env-var refs."""

    def test_no_hardcoded_key_prefixes(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Set fake keys in env to ensure they don't bleed into wrappers
        monkeypatch.setenv("MIMO_API_KEY", "tp-leaked-secret")
        monkeypatch.setenv("KIMI_API_KEY", "sk-leaked-secret")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-leaked")
        for name, spec in WRAPPER_DEFINITIONS.items():
            for use_windows in (True, False):
                _, contents = _render_wrapper(
                    name, spec, use_windows=use_windows,
                )
                # No actual secret values
                assert "tp-leaked-secret" not in contents, (
                    f"{name} ({'win' if use_windows else 'posix'}): "
                    f"leaked MIMO_API_KEY"
                )
                assert "sk-leaked-secret" not in contents, (
                    f"{name} ({'win' if use_windows else 'posix'}): "
                    f"leaked KIMI_API_KEY"
                )
                assert "sk-deepseek-leaked" not in contents


# ---------------------------------------------------------------------------
# install_wrappers
# ---------------------------------------------------------------------------


class TestInstallWrappers:
    def test_writes_all_files(self, tmp_path: Path) -> None:
        result = install_wrappers(target_dir=tmp_path, use_windows=False)
        # Each definition got installed
        for name in WRAPPER_DEFINITIONS:
            assert name in result
            assert result[name]["status"] == "installed"
            assert (tmp_path / name).exists()

    def test_windows_writes_cmd_files(self, tmp_path: Path) -> None:
        result = install_wrappers(target_dir=tmp_path, use_windows=True)
        for name in WRAPPER_DEFINITIONS:
            assert (tmp_path / f"{name}.cmd").exists()

    def test_only_filter(self, tmp_path: Path) -> None:
        result = install_wrappers(
            target_dir=tmp_path, only=["claude-mimo", "claude-deepseek"],
            use_windows=False,
        )
        assert (tmp_path / "claude-mimo").exists()
        assert (tmp_path / "claude-deepseek").exists()
        # Others NOT installed
        assert not (tmp_path / "claude-glm").exists()
        assert not (tmp_path / "claude-qwen").exists()

    def test_unknown_wrapper_in_only(self, tmp_path: Path) -> None:
        result = install_wrappers(
            target_dir=tmp_path, only=["claude-nonexistent"],
            use_windows=False,
        )
        assert result["claude-nonexistent"]["status"] == "skipped"
        assert "unknown" in result["claude-nonexistent"]["reason"].lower()

    def test_overwrite_false_preserves_existing(self, tmp_path: Path) -> None:
        # Pre-create one wrapper with sentinel content
        existing = tmp_path / "claude-mimo"
        existing.write_text("# operator's custom wrapper\n", encoding="utf-8")
        result = install_wrappers(
            target_dir=tmp_path, only=["claude-mimo"],
            use_windows=False, overwrite=False,
        )
        assert result["claude-mimo"]["status"] == "skipped-exists"
        # File untouched
        assert existing.read_text(encoding="utf-8") == \
               "# operator's custom wrapper\n"

    def test_overwrite_true_replaces_existing(self, tmp_path: Path) -> None:
        existing = tmp_path / "claude-mimo"
        existing.write_text("# stale content", encoding="utf-8")
        result = install_wrappers(
            target_dir=tmp_path, only=["claude-mimo"],
            use_windows=False, overwrite=True,
        )
        assert result["claude-mimo"]["status"] == "installed"
        # File now has the generated wrapper content
        new_content = existing.read_text(encoding="utf-8")
        assert "#!/bin/bash" in new_content
        assert "ANTHROPIC_BASE_URL" in new_content

    def test_posix_files_are_executable(self, tmp_path: Path) -> None:
        if os.name == "nt":
            pytest.skip("Executable bit not meaningful on Windows")
        install_wrappers(target_dir=tmp_path, use_windows=False)
        f = tmp_path / "claude-mimo"
        # +x for user
        mode = f.stat().st_mode
        assert mode & stat.S_IXUSR, "wrapper must be user-executable"


# ---------------------------------------------------------------------------
# list_wrappers
# ---------------------------------------------------------------------------


class TestListWrappers:
    def test_empty_dir_shows_all_uninstalled(self, tmp_path: Path) -> None:
        wrappers = list_wrappers(target_dir=tmp_path)
        assert len(wrappers) == len(WRAPPER_DEFINITIONS)
        for w in wrappers:
            assert w["installed"] is False

    def test_partial_install_shown_correctly(self, tmp_path: Path) -> None:
        install_wrappers(
            target_dir=tmp_path, only=["claude-mimo"],
            use_windows=False,
        )
        wrappers = list_wrappers(target_dir=tmp_path)
        by_name = {w["name"]: w for w in wrappers}
        # Note: list_wrappers uses _is_windows() for the suffix.  On a
        # POSIX-default test env it looks for "claude-mimo"; with the
        # install_wrappers above using use_windows=False, the file is
        # at "claude-mimo" (no suffix), so installed should be True.
        if not _is_windows():
            assert by_name["claude-mimo"]["installed"] is True
            assert by_name["claude-glm"]["installed"] is False

    def test_key_present_reflected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MIMO_API_KEY", "tp-test")
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        wrappers = list_wrappers(target_dir=tmp_path)
        by_name = {w["name"]: w for w in wrappers}
        assert by_name["claude-mimo"]["key_present"] is True
        assert by_name["claude-kimi"]["key_present"] is False


# ---------------------------------------------------------------------------
# Path hint
# ---------------------------------------------------------------------------


class TestPathHint:
    def test_returns_none_when_dir_on_path(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from harness.engines.wrapper_scripts import DEFAULT_WRAPPER_DIR
        resolved = str(DEFAULT_WRAPPER_DIR.resolve())
        monkeypatch.setenv("PATH", f"{resolved}{os.pathsep}/other/dirs")
        assert get_path_hint() is None

    def test_returns_hint_when_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PATH", "/only/some/random/dirs")
        hint = get_path_hint()
        assert hint is not None
        assert ".harness" in hint or "harness" in hint


# ---------------------------------------------------------------------------
# CLI: harness engines install-wrappers + list-wrappers
# ---------------------------------------------------------------------------


class TestCli:
    def test_install_wrappers_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Redirect DEFAULT_WRAPPER_DIR to tmp via monkeypatching
        monkeypatch.setattr(
            "harness.engines.wrapper_scripts.DEFAULT_WRAPPER_DIR",
            tmp_path / "bin",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "install-wrappers"])
        assert result.exit_code == 0
        assert "INSTALLED" in result.output or "EXISTS" in result.output

    def test_list_wrappers_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "harness.engines.wrapper_scripts.DEFAULT_WRAPPER_DIR",
            tmp_path / "bin",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "list-wrappers"])
        assert result.exit_code == 0
        # Table headers visible
        assert "wrapper" in result.output.lower()
        assert "installed" in result.output.lower()
