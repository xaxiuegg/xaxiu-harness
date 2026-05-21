"""Tests for harness.coord.planner."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from harness.coord.planner import _new_run_id, _read_repo_tree, plan, write_plan
from harness.coord.schemas import WavePlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_plan_dict(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "spec_path": "spec.md",
        "created_at": "2026-05-20T22:00:00+00:00",
        "planner_engine": "kimi",
        "planner_model": "kimi-latest",
        "tasks": [
            {
                "worker_id": "worker-1",
                "title": "Fix bug",
                "description": "Fix the off-by-one error",
                "read_set": ["src/foo.py"],
                "write_set": ["src/foo.py"],
                "test_set": ["tests/test_foo.py"],
                "depends_on": [],
                "steps": [
                    {
                        "step_id": "step-1",
                        "kind": "edit",
                        "instruction": "Change foo to bar",
                        "target_files": ["src/foo.py"],
                        "expected_diff_lines": 5,
                        "required_tests": ["tests/test_foo.py"],
                    }
                ],
                "estimated_kimi_minutes": 10,
                "max_context_tokens": 30000,
            }
        ],
        "integration_strategy": "squash",
        "notes": "",
    }


def _make_dispatch_result(text: str, success: bool = True) -> MagicMock:
    result = MagicMock()
    result.success = success
    result.text = text
    result.error = None if success else "mock_error"
    return result


# ---------------------------------------------------------------------------
# _new_run_id
# ---------------------------------------------------------------------------

def test_new_run_id_format() -> None:
    rid = _new_run_id()
    assert re.fullmatch(r"\d{8}T\d{6}-[a-z0-9]{4}", rid)


# ---------------------------------------------------------------------------
# _read_repo_tree
# ---------------------------------------------------------------------------

def test_read_repo_tree_truncates(tmp_path: Path) -> None:
    # Create enough files to trigger truncation
    for i in range(250):
        (tmp_path / f"file{i}.txt").write_text("x")
    tree = _read_repo_tree(tmp_path, max_lines=10)
    lines = tree.splitlines()
    assert len(lines) == 11
    assert "(truncated" in lines[-1]


def test_read_repo_tree_skips_git_and_pycache(tmp_path: Path) -> None:
    (tmp_path / ".git" / "config").parent.mkdir(parents=True)
    (tmp_path / ".git" / "config").write_text("[core]")
    (tmp_path / "src" / "__pycache__" / "foo.cpython-311.pyc").parent.mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "foo.cpython-311.pyc").write_text("x")
    (tmp_path / "real.py").write_text("hello")
    tree = _read_repo_tree(tmp_path)
    assert "real.py" in tree
    assert ".git" not in tree
    assert "__pycache__" not in tree


# ---------------------------------------------------------------------------
# plan — happy path
# ---------------------------------------------------------------------------

def test_plan_happy_path_with_code_fence(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    plan_data = _valid_plan_dict(run_id)
    json_text = json.dumps(plan_data)
    fenced = f"```json\n{json_text}\n```"

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(fenced),
    ) as mock_dispatch:
        result = plan(spec, run_id=run_id, project_root=tmp_path)

    assert isinstance(result, WavePlan)
    assert result.run_id == run_id
    mock_dispatch.assert_called_once()


def test_plan_json_without_code_fence(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    plan_data = _valid_plan_dict(run_id)
    json_text = json.dumps(plan_data)

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json_text),
    ) as mock_dispatch:
        result = plan(spec, run_id=run_id, project_root=tmp_path)

    assert isinstance(result, WavePlan)
    assert result.run_id == run_id
    mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# plan — retry logic
# ---------------------------------------------------------------------------

def test_plan_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    bad_data = {"schema_version": 1}  # missing required fields
    good_data = _valid_plan_dict(run_id)

    responses = [
        _make_dispatch_result(json.dumps(bad_data)),
        _make_dispatch_result(json.dumps(good_data)),
    ]

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        side_effect=responses,
    ) as mock_dispatch:
        result = plan(spec, run_id=run_id, project_root=tmp_path, max_retries=1)

    assert isinstance(result, WavePlan)
    assert result.run_id == run_id
    assert mock_dispatch.call_count == 2


def test_plan_raises_validation_error_after_exhausting_retries(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    bad_data = {"schema_version": 1}  # missing required fields

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json.dumps(bad_data)),
    ) as mock_dispatch:
        with pytest.raises(ValidationError):
            plan(spec, run_id=run_id, project_root=tmp_path, max_retries=1)

    assert mock_dispatch.call_count == 2


def test_plan_auto_generates_run_id(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    run_id = "20260520T220000-ab12"
    plan_data = _valid_plan_dict(run_id)

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json.dumps(plan_data)),
    ):
        result = plan(spec, project_root=tmp_path)

    assert isinstance(result, WavePlan)
    assert re.fullmatch(r"\d{8}T\d{6}-[a-z0-9]{4}", result.run_id)


# ---------------------------------------------------------------------------
# write_plan
# ---------------------------------------------------------------------------

def test_write_plan_atomic(tmp_path: Path) -> None:
    run_id = "20260520T220000-ab12"
    plan_obj = WavePlan.model_validate(_valid_plan_dict(run_id))
    run_dir = tmp_path / "runs" / run_id
    out = write_plan(plan_obj, run_dir)
    assert out == run_dir / "plan.json"
    assert out.exists()
    raw = out.read_text(encoding="utf-8")
    restored = WavePlan.model_validate_json(raw)
    assert restored.run_id == run_id
    # temp file should not linger
    assert not (run_dir / "plan.json.tmp").exists()
