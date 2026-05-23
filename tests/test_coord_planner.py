"""Tests for harness.coord.planner."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from harness.coord.planner import (
    _extract_strict_paths,
    _new_run_id,
    _read_repo_tree,
    plan,
    write_plan,
)
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
        result = plan(spec, run_id=run_id, project_root=tmp_path, skip_lint=True)

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
        result = plan(spec, run_id=run_id, project_root=tmp_path, skip_lint=True)

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
        result = plan(spec, run_id=run_id, project_root=tmp_path, max_retries=1, skip_lint=True)

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
            plan(spec, run_id=run_id, project_root=tmp_path, max_retries=1, skip_lint=True)

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
        result = plan(spec, project_root=tmp_path, skip_lint=True)

    assert isinstance(result, WavePlan)
    assert re.fullmatch(r"\d{8}T\d{6}-[a-z0-9]{4}", result.run_id)


# ---------------------------------------------------------------------------
# WIRE-RUN-ID-AUTOGEN (2026-05-22) — D-NEW-4
# ---------------------------------------------------------------------------

def test_plan_replaces_malformed_run_id_with_autogen(tmp_path: Path, caplog) -> None:
    """A free-form run_id (e.g. 'my-smoke-1') gets replaced with a conformant
    auto-generated one + a warning is emitted, rather than failing with a
    cryptic pydantic pattern-mismatch."""
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    # The dispatch stub returns a plan; the planner overwrites data['run_id']
    # with its sanitised value before validation, so even an arbitrary plan
    # data run_id won't survive.
    plan_data = _valid_plan_dict("20260520T220000-ab12")

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json.dumps(plan_data)),
    ):
        import logging
        with caplog.at_level(logging.WARNING, logger="harness.coord.planner"):
            result = plan(
                spec, run_id="my-free-form-label",
                project_root=tmp_path, skip_lint=True,
            )

    # result.run_id is the auto-generated conformant one (not the free-form input)
    assert re.fullmatch(r"\d{8}T\d{6}-[a-z0-9]{4}", result.run_id)
    assert result.run_id != "my-free-form-label"
    # operator sees a clear warning that their label was replaced
    assert any("my-free-form-label" in rec.message for rec in caplog.records)


def test_plan_keeps_conformant_run_id_unchanged(tmp_path: Path) -> None:
    """When the operator passes a properly-formatted run_id, it's preserved."""
    spec = tmp_path / "spec.md"
    spec.write_text("# Do a thing")
    plan_data = _valid_plan_dict("20260520T220000-ab12")

    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json.dumps(plan_data)),
    ):
        result = plan(
            spec, run_id="20260520T220000-ab12",
            project_root=tmp_path, skip_lint=True,
        )

    assert result.run_id == "20260520T220000-ab12"


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


# ---------------------------------------------------------------------------
# W5-BB strict-path parsing
# ---------------------------------------------------------------------------

def test_extract_strict_paths_returns_empty_when_section_missing() -> None:
    spec = "# Title\n\n## Goal\nDo stuff.\n"
    assert _extract_strict_paths(spec) == []


def test_extract_strict_paths_parses_bullet_list() -> None:
    spec = (
        "# Title\n\n"
        "## Goal\nDo stuff.\n\n"
        "## Strict Paths\n"
        "- coord/orchestrator-demo/2026-05-22T094327Z.md\n"
        "- coord/orchestrator-demo/2026-05-22T094327Z.json\n\n"
        "## Why\nBecause.\n"
    )
    assert _extract_strict_paths(spec) == [
        "coord/orchestrator-demo/2026-05-22T094327Z.md",
        "coord/orchestrator-demo/2026-05-22T094327Z.json",
    ]


def test_extract_strict_paths_accepts_underscore_header() -> None:
    """Operator may write either `Strict Paths` or `STRICT_PATHS`."""
    spec = (
        "## STRICT_PATHS\n"
        "- coord/x.md\n"
    )
    assert _extract_strict_paths(spec) == ["coord/x.md"]


def test_extract_strict_paths_strips_backticks_and_quotes() -> None:
    """Operators often wrap paths in `code` or quotes; strip them."""
    spec = (
        "## Strict Paths\n"
        "- `coord/a.md`\n"
        "- \"coord/b.md\"\n"
        "- coord/c.md\n"
    )
    assert _extract_strict_paths(spec) == [
        "coord/a.md", "coord/b.md", "coord/c.md",
    ]


def test_plan_strict_paths_override_llm_output(tmp_path: Path) -> None:
    """W5-BB: operator's spec-declared strict_paths override the LLM's
    emission of the same field — the spec is the binding source."""
    spec = tmp_path / "s.md"
    spec.write_text(
        "## Goal\nDo it.\n\n"
        "## Strict Paths\n"
        "- coord/operator/required.md\n",
        encoding="utf-8",
    )
    plan_data = _valid_plan_dict("20260520T220000-ab12")
    # LLM emits a different strict_paths value — the planner should
    # override it with the operator's declaration.
    plan_data["strict_paths"] = ["llm/whatever.md"]
    with patch(
        "harness.engines.dispatcher.dispatch_packet",
        return_value=_make_dispatch_result(json.dumps(plan_data)),
    ):
        result = plan(
            spec, run_id="20260520T220000-ab12",
            project_root=tmp_path, skip_lint=True,
        )
    assert result.strict_paths == ["coord/operator/required.md"]
