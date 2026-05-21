"""Tests for harness.adapters.loader."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from harness.adapters.loader import (
    ALLOWED_TEMPLATES,
    _repo_root,
    load_project_adapter,
    load_template,
    list_templates,
    resolve_placeholders,
)
from harness.adapters.schema import (
    AdapterConfig,
    ObserverConfig,
    StatusTrackingConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_adapter_yaml(root: Path, project_name: str, extra: dict | None = None) -> Path:
    """Write a minimal harness-adapter.yaml under <root>/adapters/<project_name>."""
    adapter_dir = root / "adapters" / project_name
    adapter_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": project_name,
        "project_root": str(adapter_dir / "project"),
        "status_tracking": {"backend": "csv", "config": {"csv_path": "STATUS.csv"}},
        "observer": {
            "enabled": True,
            "cadence_minutes": 30,
            "daily_retro_time": "17:00",
            "flag_patterns": [".*FAIL.*"],
        },
        "routing_rules": [],
        "scheduled_tasks": [],
    }
    if extra:
        data.update(extra)
    (adapter_dir / "project").mkdir(parents=True, exist_ok=True)
    path = adapter_dir / "harness-adapter.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------
def test_list_templates() -> None:
    assert list_templates() == sorted(ALLOWED_TEMPLATES)


# ---------------------------------------------------------------------------
# resolve_placeholders
# ---------------------------------------------------------------------------
def test_resolve_placeholders_basic() -> None:
    text = "root: {{PROJECT_ROOT}}"
    assert resolve_placeholders(text, r"C:\Users\foo\project") == "root: C:/Users/foo/project"


def test_resolve_placeholders_no_placeholder() -> None:
    text = "root: /foo/bar"
    assert resolve_placeholders(text, "/baz") == text


# ---------------------------------------------------------------------------
# load_template – name validation
# ---------------------------------------------------------------------------
def test_load_template_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown template"):
        load_template("evil-template")


@patch("harness.adapters.loader._repo_root")
def test_load_template_missing_file(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    templates_dir = tmp_path / "adapters" / "templates"
    templates_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        load_template("warehouse-style")


@patch("harness.adapters.loader._repo_root")
def test_load_template_with_placeholder(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    templates_dir = tmp_path / "adapters" / "templates"
    templates_dir.mkdir(parents=True)
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    template_text = yaml.safe_dump(
        {
            "name": "demo",
            "project_root": "{{PROJECT_ROOT}}",
            "status_tracking": {"backend": "csv", "config": {"csv_path": "STATUS.csv"}},
            "observer": {
                "enabled": True,
                "cadence_minutes": 30,
                "daily_retro_time": "17:00",
                "flag_patterns": [".*FAIL.*"],
            },
            "routing_rules": [],
            "scheduled_tasks": [],
        }
    )
    (templates_dir / "warehouse-style.yaml").write_text(template_text, encoding="utf-8")

    cfg = load_template("warehouse-style", project_root=str(project_dir))
    # resolve_placeholders normalizes backslashes to forward slashes
    assert cfg.project_root == str(project_dir).replace("\\", "/")


# ---------------------------------------------------------------------------
# load_project_adapter – name validation
# ---------------------------------------------------------------------------
def test_load_project_adapter_invalid_name() -> None:
    with pytest.raises(ValueError, match="project_name must match"):
        load_project_adapter("../../etc/passwd")


@patch("harness.adapters.loader._repo_root")
def test_load_project_adapter_missing_file(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    with pytest.raises(FileNotFoundError):
        load_project_adapter("nonexistent")


# ---------------------------------------------------------------------------
# Path security checks – MED-2 / MED-3
# ---------------------------------------------------------------------------
@patch("harness.adapters.loader._repo_root")
def test_project_root_not_absolute(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    _make_adapter_yaml(tmp_path, "bad-root", {"project_root": "relative/path"})
    with pytest.raises(ValueError, match="project_root must be an absolute path"):
        load_project_adapter("bad-root")


@patch("harness.adapters.loader._repo_root")
def test_project_root_does_not_exist(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    _make_adapter_yaml(tmp_path, "bad-root", {"project_root": str(tmp_path / "missing")})
    with pytest.raises(ValueError, match="project_root does not exist"):
        load_project_adapter("bad-root")


@patch("harness.adapters.loader._repo_root")
def test_project_root_under_system_dir(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    windir = os.environ.get("WINDIR", r"C:\Windows")
    _make_adapter_yaml(tmp_path, "bad-root", {"project_root": windir})
    with pytest.raises(ValueError, match="project_root must not be under system directories"):
        load_project_adapter("bad-root")


@patch("harness.adapters.loader._repo_root")
def test_csv_path_escapes_project_root(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    project_dir = tmp_path / "adapters" / "escaper" / "project"
    project_dir.mkdir(parents=True)
    _make_adapter_yaml(
        tmp_path,
        "escaper",
        {
            "project_root": str(project_dir),
            "status_tracking": {
                "backend": "csv",
                "config": {"csv_path": "../../../evil.csv"},
            },
        },
    )
    with pytest.raises(ValueError, match="csv_path escapes project_root"):
        load_project_adapter("escaper")


@patch("harness.adapters.loader._repo_root")
def test_markdown_path_escapes_project_root(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    project_dir = tmp_path / "adapters" / "escaper" / "project"
    project_dir.mkdir(parents=True)
    _make_adapter_yaml(
        tmp_path,
        "escaper",
        {
            "project_root": str(project_dir),
            "status_tracking": {
                "backend": "markdown",
                "config": {"path": "../../../evil.md"},
            },
        },
    )
    with pytest.raises(ValueError, match="path escapes project_root"):
        load_project_adapter("escaper")


@patch("harness.adapters.loader._repo_root")
def test_load_project_adapter_success(mock_root, tmp_path: Path) -> None:
    mock_root.return_value = tmp_path
    project_dir = tmp_path / "adapters" / "good" / "project"
    project_dir.mkdir(parents=True)
    _make_adapter_yaml(tmp_path, "good", {"project_root": str(project_dir)})
    cfg = load_project_adapter("good")
    assert cfg.name == "good"
    assert cfg.project_root == str(project_dir)



# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------
def test_adapter_config_without_operator() -> None:
    cfg = AdapterConfig(
        name="legacy",
        project_root="C:\\legacy",
        status_tracking=StatusTrackingConfig(
            backend="csv", config={"csv_path": "STATUS.csv"}
        ),
        observer=ObserverConfig(),
    )
    assert cfg.operator is None


# ---------------------------------------------------------------------------
# Real template smoke tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", list_templates())
def test_real_template_loads(name: str) -> None:
    cfg = load_template(name)
    assert cfg.operator is not None
    assert cfg.operator.escalation_threshold == "L5"
    assert cfg.operator.engine_fill == "aggressive"
    assert cfg.operator.max_parallel_supervisors == 4
    assert cfg.operator.explore_on_uncertainty == "dispatch_alternatives"
    assert cfg.operator.observer_cadence_minutes == 60
    assert cfg.operator.notification_method == "file"
    assert cfg.operator.notification_target == "coord/dev_loop/escalations.md"


def test_solo_dev_template_operator_overrides() -> None:
    cfg = load_template("solo-dev")
    assert cfg.operator is not None
    assert cfg.operator.mode == "full_dev_authority"


def test_writing_content_template_operator_overrides() -> None:
    cfg = load_template("writing-content")
    assert cfg.operator is not None
    assert cfg.operator.profile == "non_technical"
    assert cfg.operator.engine_routing.get("developing") == "claude-in-session"


def test_research_comparison_template_operator_overrides() -> None:
    cfg = load_template("research-comparison")
    assert cfg.operator is not None
    assert cfg.operator.engine_routing.get("developing") == "swarm/deepseek"
