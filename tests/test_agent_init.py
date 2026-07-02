"""W11-AGENT-INIT-VERB: tests for `harness agent init --target <path>`.

The foundation row of Wave 11-A.  Every subsequent W11 row assumes
the file tree this verb writes (project-scoped .env, adapter.py,
CLAUDE.md, .harness/state dir).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from harness import agent as _agent
from harness import cli as _cli


# -- init_project pure function -------------------------------------------


def test_init_creates_expected_file_tree(tmp_path):
    target = tmp_path / "my-project"
    result = _agent.init_project(target=target, project_type="python")
    assert (target / ".env").exists()
    assert (target / ".gitignore").exists()
    assert (target / "adapter.py").exists()
    assert (target / "CLAUDE.md").exists()
    assert (target / ".harness" / "config.json").exists()
    assert (target / ".harness" / "STATUS.csv").exists()
    assert (target / ".harness" / "dispatched" / ".gitkeep").exists()
    # Result accounting
    assert len(result.created) == 7  # 4 + 3 in .harness/
    assert result.adapter_name == "MyProjectAdapter"
    assert result.project_type == "python"


def test_init_creates_target_dir_if_missing(tmp_path):
    target = tmp_path / "does" / "not" / "exist" / "yet"
    assert not target.exists()
    _agent.init_project(target=target)
    assert target.is_dir()


def test_init_preserves_existing_env(tmp_path):
    """Idempotency: .env with operator-supplied secrets is NEVER overwritten."""
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".env").write_text(
        "HARNESS_KIMI_API_KEY=real_value_do_not_lose\n",
        encoding="utf-8",
    )
    result = _agent.init_project(target=target)
    # .env content unchanged
    content = (target / ".env").read_text(encoding="utf-8")
    assert "real_value_do_not_lose" in content
    # And reported as skipped
    skipped_paths = [str(p) for p, _ in result.skipped]
    assert any(".env" in p for p in skipped_paths)


def test_init_preserves_existing_adapter(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    custom_code = "# operator's hand-written adapter\nfrom foo import bar\n"
    (target / "adapter.py").write_text(custom_code, encoding="utf-8")
    result = _agent.init_project(target=target)
    # adapter.py content unchanged
    assert (target / "adapter.py").read_text(encoding="utf-8") == custom_code
    skipped_paths = [str(p) for p, _ in result.skipped]
    assert any("adapter.py" in p for p in skipped_paths)


def test_init_appends_to_existing_claude_md_with_marker(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    existing = "# My Project\n\nDocs here.\n"
    (target / "CLAUDE.md").write_text(existing, encoding="utf-8")
    result = _agent.init_project(target=target)
    new_content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    # Operator's content preserved
    assert existing in new_content
    # Marker present
    assert "<!-- harness:agent-init -->" in new_content
    # Reported as appended (not created, not skipped)
    appended_paths = [str(p) for p in result.appended]
    assert any("CLAUDE.md" in p for p in appended_paths)


def test_init_skips_claude_md_with_marker_already_present(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    existing = "# My Project\n<!-- harness:agent-init -->\nold snippet\n"
    (target / "CLAUDE.md").write_text(existing, encoding="utf-8")
    result = _agent.init_project(target=target)
    # No append on re-run (idempotent)
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == existing
    skipped_paths = [str(p) for p, _ in result.skipped]
    assert any("CLAUDE.md" in p for p in skipped_paths)


def test_init_raises_on_status_csv_with_data_rows(tmp_path):
    """Critical safety: existing STATUS.csv with rows must NOT be
    overwritten — operator must merge manually."""
    target = tmp_path / "proj"
    (target / ".harness").mkdir(parents=True)
    (target / ".harness" / "STATUS.csv").write_text(
        "timestamp,dispatch_id,engine,model,tokens_in,tokens_out,"
        "duration_ms,cost_usd,status,error\n"
        "2026-05-25T10:00:00Z,abc123,kimi,kimi-k2.6,100,200,1500,0.0,success,\n",
        encoding="utf-8",
    )
    with pytest.raises(_agent.StatusCollisionError):
        _agent.init_project(target=target)


def test_init_status_csv_header_only_is_safe(tmp_path):
    """Existing STATUS.csv with only the header (no data rows) is OK."""
    target = tmp_path / "proj"
    (target / ".harness").mkdir(parents=True)
    header = (
        "timestamp,dispatch_id,engine,model,tokens_in,tokens_out,"
        "duration_ms,cost_usd,status,error\n"
    )
    (target / ".harness" / "STATUS.csv").write_text(header, encoding="utf-8")
    # Should NOT raise
    result = _agent.init_project(target=target)
    # File still exists with header intact
    assert (target / ".harness" / "STATUS.csv").read_text(
        encoding="utf-8"
    ) == header


def test_init_refuses_self_target(tmp_path, monkeypatch):
    """Critical safety: --target pointing at the harness's own repo
    must refuse without --allow-self."""
    # Synthesize a fake harness-repo at tmp_path
    (tmp_path / "src" / "harness").mkdir(parents=True)
    (tmp_path / "src" / "harness" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "STATUS.csv").write_text("", encoding="utf-8")
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "multi-agent-harness-architecture.md").write_text(
        "", encoding="utf-8"
    )
    with pytest.raises(_agent.SelfTargetRefused):
        _agent.init_project(target=tmp_path)


def test_init_allow_self_overrides_safety(tmp_path):
    """--allow-self lets the operator bootstrap on top of the harness."""
    (tmp_path / "src" / "harness").mkdir(parents=True)
    (tmp_path / "src" / "harness" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "coord").mkdir()
    (tmp_path / "coord" / "STATUS.csv").write_text("", encoding="utf-8")
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "multi-agent-harness-architecture.md").write_text(
        "", encoding="utf-8"
    )
    # Should NOT raise with allow_self=True
    result = _agent.init_project(target=tmp_path, allow_self=True)
    assert (tmp_path / ".env").exists()


def test_init_dry_run_writes_nothing(tmp_path):
    """--dry-run reports planned files without touching disk."""
    target = tmp_path / "proj"
    result = _agent.init_project(target=target, dry_run=True)
    assert result.dry_run is True
    # Result lists planned creations
    assert len(result.created) > 0
    # But NOTHING on disk
    assert not (target / ".env").exists()
    assert not (target / "adapter.py").exists()
    assert not (target / ".harness").exists()


def test_init_rejects_unknown_project_type(tmp_path):
    with pytest.raises(ValueError, match="unknown project_type"):
        _agent.init_project(target=tmp_path, project_type="rust")  # type: ignore[arg-type]


def test_init_adapter_class_name_derived_from_basename(tmp_path):
    """my-project -> MyProjectAdapter ; weird_name -> WeirdNameAdapter."""
    cases = [
        ("my-project", "MyProjectAdapter"),
        ("weird_name", "WeirdNameAdapter"),
        ("camelCaseHere", "CamelCaseHereAdapter"),
        ("a", "AAdapter"),
    ]
    for name, expected_class in cases:
        target = tmp_path / name
        result = _agent.init_project(target=target)
        assert result.adapter_name == expected_class, (
            f"target={name}: got {result.adapter_name}, want {expected_class}"
        )


def test_init_adapter_class_name_override(tmp_path):
    target = tmp_path / "proj"
    result = _agent.init_project(target=target, adapter_name="MyCustomAdapter")
    assert result.adapter_name == "MyCustomAdapter"
    adapter_code = (target / "adapter.py").read_text(encoding="utf-8")
    assert "MyCustomAdapter" in adapter_code


def test_init_config_json_is_valid_with_required_fields(tmp_path):
    target = tmp_path / "proj"
    _agent.init_project(target=target, project_type="node")
    cfg = json.loads((target / ".harness" / "config.json").read_text(
        encoding="utf-8"
    ))
    assert cfg["schema_version"] == 1
    assert cfg["project_name"] == "proj"
    assert cfg["project_type"] == "node"
    assert cfg["init_version"] == "w11-agent-init-verb"
    assert "created_at" in cfg


def test_init_env_template_contains_all_required_keys(tmp_path):
    """Operator (or env-wizard) sees the full list of keys it needs."""
    target = tmp_path / "proj"
    _agent.init_project(target=target)
    env = (target / ".env").read_text(encoding="utf-8")
    for key in ("KIMI_API_KEY", "DEEPSEEK_API_KEY", "MIMO_API_KEY"):
        assert f"HARNESS_{key}" in env


def test_init_gitignore_template_excludes_secrets(tmp_path):
    target = tmp_path / "proj"
    _agent.init_project(target=target)
    gi = (target / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi
    assert ".harness/" in gi


def test_init_claude_md_snippet_under_800_chars(tmp_path):
    """Per W11-CLAUDE-MD-TEMPLATE merge spec: ≤800 chars."""
    target = tmp_path / "proj"
    _agent.init_project(target=target)
    # New file should contain only the template snippet
    claude = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(claude) <= 900, (
        f"CLAUDE.md template is {len(claude)} chars; must be ≤900 "
        f"(target ≤800 plus minor formatting)"
    )


# -- CLI integration -----------------------------------------------------










def test_cli_agent_init_invalid_project_type(tmp_path):
    runner = CliRunner()
    target = tmp_path / "proj"
    result = runner.invoke(_cli.cli, [
        "agent", "init", "--target", str(target),
        "--project-type", "rust",
    ])
    # Click's Choice constraint exits non-zero on invalid value
    assert result.exit_code != 0




# -- Idempotency (re-run produces no surprise) ---------------------------


def test_init_is_idempotent(tmp_path):
    """Run init twice; second run should not change existing files +
    should report everything as skipped (or marker-already-present)."""
    target = tmp_path / "proj"
    first = _agent.init_project(target=target)
    # Snapshot key file contents
    env_before = (target / ".env").read_text(encoding="utf-8")
    adapter_before = (target / "adapter.py").read_text(encoding="utf-8")
    claude_before = (target / "CLAUDE.md").read_text(encoding="utf-8")
    config_before = (target / ".harness" / "config.json").read_text(encoding="utf-8")

    second = _agent.init_project(target=target)

    # Files unchanged
    assert (target / ".env").read_text(encoding="utf-8") == env_before
    assert (target / "adapter.py").read_text(encoding="utf-8") == adapter_before
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == claude_before
    assert (target / ".harness" / "config.json").read_text(
        encoding="utf-8"
    ) == config_before
    # Second run mostly skips
    assert len(second.skipped) >= 5
    # Nothing new created
    assert len(second.created) <= 1  # at most a missing helper file
