"""Tests for NL → harness-adapter.yaml translation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from harness.adapters.from_description import (
    _dispatch_direct,
    _dispatch_via_packet,
    _extract_adapter_yaml,
    _map_engine,
    generate_adapter_from_nl,
)
from harness.adapters.schema import AdapterConfig, ObserverConfig, StatusTrackingConfig
from harness.cli import cli
from harness.engines.base import EngineResponse
from harness.errors import DispatchExhausted, SchemaViolation


# ---------------------------------------------------------------------------
# _extract_adapter_yaml
# ---------------------------------------------------------------------------


def test_extract_adapter_yaml_success() -> None:
    text = "prelude\n<<<ADAPTER\nname: demo\nproject_root: /tmp\nADAPTER>>>\nfooter"
    assert _extract_adapter_yaml(text) == "name: demo\nproject_root: /tmp"


def test_extract_adapter_yaml_missing_start() -> None:
    with pytest.raises(ValueError, match="Missing <<<ADAPTER"):
        _extract_adapter_yaml("no markers")


def test_extract_adapter_yaml_missing_end() -> None:
    with pytest.raises(ValueError, match="Missing ADAPTER>>>"):
        _extract_adapter_yaml("<<<ADAPTER\nname: demo")


def test_extract_adapter_yaml_no_content_between_markers() -> None:
    with pytest.raises(ValueError, match="No YAML content between markers"):
        _extract_adapter_yaml("<<<ADAPTERADAPTER>>>")


def test_map_engine_unsupported() -> None:
    with pytest.raises(ValueError, match="Unsupported engine"):
        _map_engine("unknown")


# ---------------------------------------------------------------------------
# _dispatch_via_packet
# ---------------------------------------------------------------------------


@patch("harness.adapters.from_description.dispatch_packet")
def test_dispatch_via_packet_success(mock_dispatch_packet) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=True, text="hello world", error=None
    )
    result = _dispatch_via_packet("proj", "prompt text", "kimi")
    assert result == "hello world"
    assert mock_dispatch_packet.call_args.kwargs["force_engine"] == "kimi"


@patch("harness.adapters.from_description._dispatch_direct")
@patch("harness.adapters.from_description.dispatch_packet")
def test_dispatch_via_packet_adapter_load_fallback_success(
    mock_dispatch_packet, mock_dispatch_direct
) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=False, text="", error="adapter_load_failed: not found"
    )
    mock_dispatch_direct.return_value = "fallback text"
    result = _dispatch_via_packet("proj", "prompt text", "kimi")
    assert result == "fallback text"
    mock_dispatch_direct.assert_called_once_with("prompt text", "kimi")


@patch("harness.adapters.from_description.get_engine")
@patch("harness.adapters.from_description.dispatch_packet")
def test_dispatch_via_packet_adapter_load_fallback_engine_unavailable(
    mock_dispatch_packet, mock_get_engine
) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=False, text="", error="adapter_load_failed: not found"
    )
    mock_get_engine.side_effect = RuntimeError("engine not found")
    with pytest.raises(DispatchExhausted, match="unavailable"):
        _dispatch_via_packet("proj", "prompt text", "kimi")


@patch("harness.adapters.from_description.get_engine")
@patch("harness.adapters.from_description.dispatch_packet")
def test_dispatch_via_packet_adapter_load_fallback_dispatch_fails(
    mock_dispatch_packet, mock_get_engine
) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=False, text="", error="adapter_load_failed: not found"
    )
    mock_engine = MagicMock()
    mock_engine.dispatch.return_value = EngineResponse(
        success=False, text="", latency_ms=0, error="rate limit"
    )
    mock_get_engine.return_value = mock_engine
    with pytest.raises(DispatchExhausted, match="dispatch failed"):
        _dispatch_via_packet("proj", "prompt text", "kimi")


@patch("harness.adapters.from_description.dispatch_packet")
def test_dispatch_via_packet_other_error(mock_dispatch_packet) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=False, text="", error="some random error"
    )
    with pytest.raises(DispatchExhausted, match="dispatch failed"):
        _dispatch_via_packet("proj", "prompt text", "kimi")


# ---------------------------------------------------------------------------
# _dispatch_direct
# ---------------------------------------------------------------------------


@patch("harness.adapters.from_description.get_engine")
def test_dispatch_direct_success(mock_get_engine) -> None:
    mock_engine = MagicMock()
    mock_engine.dispatch.return_value = EngineResponse(
        success=True, text="direct response", latency_ms=0
    )
    mock_get_engine.return_value = mock_engine
    result = _dispatch_direct("prompt", "kimi")
    assert result == "direct response"


@patch("harness.adapters.from_description.get_engine")
def test_dispatch_direct_engine_unavailable(mock_get_engine) -> None:
    mock_get_engine.side_effect = RuntimeError("not found")
    with pytest.raises(DispatchExhausted, match="unavailable"):
        _dispatch_direct("prompt", "kimi")


@patch("harness.adapters.from_description.get_engine")
def test_dispatch_direct_dispatch_fails(mock_get_engine) -> None:
    mock_engine = MagicMock()
    mock_engine.dispatch.return_value = EngineResponse(
        success=False, text="", latency_ms=0, error="rate limit"
    )
    mock_get_engine.return_value = mock_engine
    with pytest.raises(DispatchExhausted, match="dispatch failed"):
        _dispatch_direct("prompt", "kimi")


# ---------------------------------------------------------------------------
# generate_adapter_from_nl
# ---------------------------------------------------------------------------


def _valid_yaml_response(project: str = "demo") -> str:
    return (
        "<<<ADAPTER\n"
        f"name: {project}\n"
        "project_root: \"{{PROJECT_ROOT}}\"\n"
        "status_tracking:\n"
        "  backend: csv\n"
        "  config:\n"
        "    csv_path: STATUS.csv\n"
        "observer:\n"
        "  cadence_minutes: 60\n"
        "ADAPTER>>>"
    )


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_success(mock_dispatch) -> None:
    mock_dispatch.return_value = _valid_yaml_response("myproj")
    cfg = generate_adapter_from_nl(project="myproj", description="A test project.")
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert cfg.project_root == "{{PROJECT_ROOT}}"


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_retries_then_succeeds(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nname: bad\nunknown_field: 123\nADAPTER>>>"
    good = _valid_yaml_response("myproj")
    mock_dispatch.side_effect = [bad, good]

    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", max_retries=1
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_exhausted_raises(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nname: bad\nunknown_field: 123\nADAPTER>>>"
    mock_dispatch.return_value = bad

    with pytest.raises(SchemaViolation, match="Adapter validation failed"):
        generate_adapter_from_nl(
            project="myproj", description="A test project.", max_retries=1
        )
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_no_markers_then_markers(mock_dispatch) -> None:
    bare = (
        "name: myproj\n"
        'project_root: "{{PROJECT_ROOT}}"\n'
        "status_tracking:\n  backend: csv\n"
        "observer:\n  cadence_minutes: 60\n"
    )
    mock_dispatch.side_effect = [bare, _valid_yaml_response("myproj")]
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", max_retries=1
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_commentary_before_after(mock_dispatch) -> None:
    text = (
        "Here is some commentary before the adapter.\n"
        "<<<ADAPTER\n"
        "name: myproj\n"
        'project_root: "{{PROJECT_ROOT}}"\n'
        "status_tracking:\n  backend: csv\n"
        "observer:\n  cadence_minutes: 60\n"
        "ADAPTER>>>\n"
        "And some commentary after."
    )
    mock_dispatch.return_value = text
    cfg = generate_adapter_from_nl(project="myproj", description="A test project.")
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_invalid_yaml_then_valid(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nkey: [unclosed\nADAPTER>>>"
    good = _valid_yaml_response("myproj")
    mock_dispatch.side_effect = [bad, good]
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", max_retries=1
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_empty_yaml_then_valid(mock_dispatch) -> None:
    bad = "<<<ADAPTER\n   \nADAPTER>>>"
    good = _valid_yaml_response("myproj")
    mock_dispatch.side_effect = [bad, good]
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", max_retries=1
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_invalid_yaml_always(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nkey: [unclosed\nADAPTER>>>"
    mock_dispatch.return_value = bad
    with pytest.raises(SchemaViolation, match="Adapter validation failed"):
        generate_adapter_from_nl(
            project="myproj", description="A test project.", max_retries=1
        )
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_validation_fails_then_succeeds(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nname: myproj\nproject_root: \"{{PROJECT_ROOT}}\"\nADAPTER>>>"
    good = _valid_yaml_response("myproj")
    mock_dispatch.side_effect = [bad, good]
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", max_retries=1
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_validation_fails_always(mock_dispatch) -> None:
    bad = "<<<ADAPTER\nname: myproj\nproject_root: \"{{PROJECT_ROOT}}\"\nADAPTER>>>"
    mock_dispatch.return_value = bad
    with pytest.raises(SchemaViolation, match="Adapter validation failed"):
        generate_adapter_from_nl(
            project="myproj", description="A test project.", max_retries=1
        )
    assert mock_dispatch.call_count == 2


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_dispatch_exhausted(mock_dispatch) -> None:
    mock_dispatch.side_effect = DispatchExhausted("engine down")
    with pytest.raises(DispatchExhausted, match="engine down"):
        generate_adapter_from_nl(project="myproj", description="A test project.")
    assert mock_dispatch.call_count == 1


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_empty_description(mock_dispatch) -> None:
    mock_dispatch.return_value = _valid_yaml_response("myproj")
    cfg = generate_adapter_from_nl(
        project="myproj", description="   \n\t  ", max_retries=0
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"


@patch("harness.adapters.from_description._dispatch_via_packet")
def test_generate_adapter_from_nl_long_description(mock_dispatch) -> None:
    mock_dispatch.return_value = _valid_yaml_response("myproj")
    long_desc = "x" * 15000
    cfg = generate_adapter_from_nl(
        project="myproj", description=long_desc, max_retries=0
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    # Verify the prompt was built with the full description
    call_args = mock_dispatch.call_args
    assert long_desc in call_args[0][1]


@patch("harness.adapters.from_description.dispatch_packet")
def test_generate_adapter_from_nl_force_engine_swarm_kimi_api(mock_dispatch_packet) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=True, text=_valid_yaml_response("myproj"), error=None
    )
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", engine="swarm/kimi-api"
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch_packet.call_count == 1
    assert mock_dispatch_packet.call_args.kwargs["force_engine"] == "kimi"


@patch("harness.adapters.from_description.dispatch_packet")
def test_generate_adapter_from_nl_force_engine_deepseek(mock_dispatch_packet) -> None:
    mock_dispatch_packet.return_value = MagicMock(
        success=True, text=_valid_yaml_response("myproj"), error=None
    )
    cfg = generate_adapter_from_nl(
        project="myproj", description="A test project.", engine="deepseek"
    )
    assert isinstance(cfg, AdapterConfig)
    assert cfg.name == "myproj"
    assert mock_dispatch_packet.call_args.kwargs["force_engine"] == "deepseek"


# ---------------------------------------------------------------------------
# CLI adapter group
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@patch("harness.cli.generate_adapter_from_nl")
@patch("harness.cli._repo_root")
def test_cli_adapter_from_description_success(
    mock_repo_root, mock_generate, runner: CliRunner, tmp_path: Path
) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    cfg = AdapterConfig(
        name="demo",
        project_root=str(tmp_path / "project"),
        status_tracking=StatusTrackingConfig(backend="csv"),
        observer=ObserverConfig(),
    )
    mock_generate.return_value = cfg

    result = runner.invoke(
        cli,
        ["adapter", "from-description", "-p", "myproj", "--description", "A test project."],
    )
    assert result.exit_code == 0
    assert "harness-adapter.yaml" in result.output
    mock_generate.assert_called_once_with(
        project="myproj", description="A test project.", engine="swarm/kimi"
    )


@patch("harness.cli._repo_root")
def test_cli_adapter_from_description_refuses_overwrite(
    mock_repo_root, runner: CliRunner, tmp_path: Path
) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    existing = adapters_dir / "myproj" / "harness-adapter.yaml"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("name: myproj\n", encoding="utf-8")

    result = runner.invoke(
        cli,
        ["adapter", "from-description", "-p", "myproj", "--description", "A test project."],
    )
    assert result.exit_code == 2
    assert "already exists" in result.output


@patch("harness.cli.generate_adapter_from_nl")
@patch("harness.cli._repo_root")
def test_cli_adapter_from_description_force_overwrite(
    mock_repo_root, mock_generate, runner: CliRunner, tmp_path: Path
) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    existing = adapters_dir / "myproj" / "harness-adapter.yaml"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("name: myproj\n", encoding="utf-8")

    cfg = AdapterConfig(
        name="demo",
        project_root=str(tmp_path / "project"),
        status_tracking=StatusTrackingConfig(backend="csv"),
        observer=ObserverConfig(),
    )
    mock_generate.return_value = cfg

    result = runner.invoke(
        cli,
        [
            "adapter",
            "from-description",
            "-p",
            "myproj",
            "--description",
            "A test project.",
            "--force",
        ],
    )
    assert result.exit_code == 0


@patch("harness.cli._repo_root")
def test_cli_adapter_list(mock_repo_root, runner: CliRunner, tmp_path: Path) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    (adapters_dir / "proj-a" / "harness-adapter.yaml").parent.mkdir(parents=True, exist_ok=True)
    (adapters_dir / "proj-a" / "harness-adapter.yaml").write_text("name: a\n", encoding="utf-8")
    (adapters_dir / "proj-b" / "harness-adapter.yaml").parent.mkdir(parents=True, exist_ok=True)
    (adapters_dir / "proj-b" / "harness-adapter.yaml").write_text("name: b\n", encoding="utf-8")
    (adapters_dir / "empty-dir").mkdir(parents=True, exist_ok=True)

    result = runner.invoke(cli, ["adapter", "list"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line]
    assert lines == ["proj-a", "proj-b"]


@patch("harness.cli.load_project_adapter")
def test_cli_adapter_validate_success(mock_load, runner: CliRunner) -> None:
    mock_load.return_value = MagicMock()
    result = runner.invoke(cli, ["adapter", "validate", "myproj"])
    assert result.exit_code == 0
    assert "valid" in result.output
    mock_load.assert_called_once_with("myproj")


@patch("harness.cli.load_project_adapter")
def test_cli_adapter_validate_failure(mock_load, runner: CliRunner) -> None:
    mock_load.side_effect = ValueError("corrupt yaml")
    result = runner.invoke(cli, ["adapter", "validate", "badproj"])
    assert result.exit_code == 1
    assert "corrupt yaml" in result.output


@patch("harness.cli.generate_adapter_from_nl")
@patch("harness.cli._repo_root")
def test_cli_adapter_from_description_description_file(
    mock_repo_root, mock_generate, runner: CliRunner, tmp_path: Path
) -> None:
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    mock_repo_root.return_value = tmp_path

    desc_file = tmp_path / "desc.txt"
    desc_file.write_text("From file.", encoding="utf-8")

    cfg = AdapterConfig(
        name="demo",
        project_root=str(tmp_path / "project"),
        status_tracking=StatusTrackingConfig(backend="csv"),
        observer=ObserverConfig(),
    )
    mock_generate.return_value = cfg

    result = runner.invoke(
        cli,
        [
            "adapter",
            "from-description",
            "-p",
            "myproj",
            "--description-file",
            str(desc_file),
        ],
    )
    assert result.exit_code == 0
    mock_generate.assert_called_once_with(
        project="myproj", description="From file.", engine="swarm/kimi"
    )
