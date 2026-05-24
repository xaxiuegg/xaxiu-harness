"""W11-ADAPTER-VALIDATE-JSON: tests for `harness adapter validate --json`.

Goal: agents need structured validation errors (path, severity, fix-hint)
they can parse + auto-correct from, not free-text human messages.

Tests cover:
  - Valid adapter -> status=ok, errors=[]
  - Missing required field -> Pydantic-derived error with field name
  - Malformed YAML -> yaml.YAMLError-derived error with line number
  - Missing file -> FileNotFoundError-derived error with create hint
  - Exit codes: 0 for valid, 1 for any error
  - Pretty output unchanged when --json not passed
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from harness import cli as _cli


# -- pure helper: _validate_exc_to_json_errors ----------------------------


def test_helper_handles_file_not_found():
    exc = FileNotFoundError("/foo/bar/adapter.yaml")
    errs = _cli._validate_exc_to_json_errors(exc)
    assert len(errs) == 1
    assert errs[0]["severity"] == "error"
    assert "/foo/bar/adapter.yaml" in errs[0]["message"]
    # Operator-friendly fix-hint
    assert "harness adapter scaffold" in errs[0]["suggested_fix"] \
        or "harness adapter from-description" in errs[0]["suggested_fix"]


def test_helper_handles_yaml_error():
    """yaml.YAMLError with problem_mark should produce a line-numbered error."""
    import yaml as _yaml
    try:
        _yaml.safe_load("not: valid: yaml: [\n  bad")
    except _yaml.YAMLError as exc:
        errs = _cli._validate_exc_to_json_errors(exc)
        assert len(errs) == 1
        assert errs[0]["field"] == "<yaml-parse>"
        # Either line is set (if problem_mark present) or message mentions parse
        assert errs[0]["line"] is None or errs[0]["line"] > 0
        assert "YAML" in errs[0]["suggested_fix"]


def test_helper_handles_pydantic_validation_error():
    """Real Pydantic validation error -> field + suggested_fix."""
    from pydantic import BaseModel, Field, ValidationError as _PVE

    class _Toy(BaseModel):
        required_field: str
        positive_int: int = Field(gt=0)

    try:
        _Toy(positive_int=-1)
    except _PVE as exc:
        errs = _cli._validate_exc_to_json_errors(exc)
        # At least 2 errors: missing required_field + positive_int violation
        assert len(errs) >= 2
        fields = [e["field"] for e in errs]
        assert "required_field" in fields
        # Each error has all 5 keys
        for e in errs:
            assert set(e.keys()) >= {
                "field", "line", "severity", "message", "suggested_fix",
            }
            assert e["severity"] == "error"


def test_helper_fallback_for_generic_exception():
    exc = RuntimeError("something weird happened")
    errs = _cli._validate_exc_to_json_errors(exc)
    assert len(errs) == 1
    assert errs[0]["field"] == "<unknown>"
    assert errs[0]["severity"] == "error"
    assert "something weird" in errs[0]["message"]


# -- CLI integration ------------------------------------------------------


def test_cli_validate_json_valid_returns_ok_status(monkeypatch):
    """When load_project_adapter succeeds, --json emits status=ok + []."""
    from harness.adapters import schema as _schema
    fake_cfg = _schema.AdapterConfig.model_construct()
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: fake_cfg,
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "myproj", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["project"] == "myproj"
    assert payload["status"] == "ok"
    assert payload["errors"] == []


def test_cli_validate_json_missing_file_returns_structured_error(monkeypatch):
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: (_ for _ in ()).throw(
            FileNotFoundError("adapters/nope/harness-adapter.yaml")
        ),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "nope", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert len(payload["errors"]) == 1
    assert "adapters/nope" in payload["errors"][0]["message"]


def test_cli_validate_json_value_error_returns_structured_error(monkeypatch):
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: (_ for _ in ()).throw(
            ValueError("project_name must match ^[a-zA-Z0-9_-]{1,64}$")
        ),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "bad!", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert "project_name" in payload["errors"][0]["message"]


def test_cli_validate_pretty_path_unchanged(monkeypatch):
    """Without --json, the existing pretty output path runs."""
    from harness.adapters import schema as _schema
    fake_cfg = _schema.AdapterConfig.model_construct()
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: fake_cfg,
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "myproj"])
    assert result.exit_code == 0
    assert "is valid" in result.output
    # Critically, the pretty output is NOT JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_cli_validate_pretty_error_path_unchanged(monkeypatch):
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: (_ for _ in ()).throw(ValueError("bad config")),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "myproj"])
    assert result.exit_code == 1
    assert "error: bad config" in result.output


def test_cli_validate_json_payload_is_parseable_json(monkeypatch):
    """Hard contract: the --json output is always valid JSON, even on error."""
    monkeypatch.setattr(
        "harness.cli.load_project_adapter",
        lambda project: (_ for _ in ()).throw(
            RuntimeError("some unexpected failure")
        ),
    )
    runner = CliRunner()
    result = runner.invoke(_cli.cli, ["adapter", "validate", "x", "--json"])
    # Must parse cleanly
    payload = json.loads(result.output)
    # And contain the expected schema
    assert "project" in payload
    assert "status" in payload
    assert "errors" in payload
    assert isinstance(payload["errors"], list)
    for err in payload["errors"]:
        assert set(err.keys()) >= {
            "field", "line", "severity", "message", "suggested_fix",
        }
