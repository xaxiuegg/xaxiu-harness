"""W11-PYTHON-SDK-API-STUBS: tests for the agent-facing SDK contract.

The functions raise NotImplementedError (real bodies land in
W11-PYTHON-SDK-API-IMPL).  Tests verify:
- imports work in a fresh Python session (no circular imports)
- signatures match the documented contract
- type stubs (.pyi) exist + parse
- DispatchResult dataclass has all expected fields with right defaults
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

import harness


# -- import surface ------------------------------------------------------


def test_harness_module_exports_dispatch():
    assert hasattr(harness, "dispatch")
    assert callable(harness.dispatch)


def test_harness_module_exports_retrieve():
    assert hasattr(harness, "retrieve")
    assert callable(harness.retrieve)


def test_harness_module_exports_budget_status():
    assert hasattr(harness, "budget_status")
    assert callable(harness.budget_status)


def test_harness_module_exports_dispatch_result_dataclass():
    assert hasattr(harness, "DispatchResult")
    # Must be a dataclass type
    import dataclasses
    assert dataclasses.is_dataclass(harness.DispatchResult)


def test_harness_module_exports_exception_types():
    for name in ("HarnessSDKError", "ResultNotFoundError",
                 "ResultCorruptedError"):
        assert hasattr(harness, name), f"missing exception {name}"
        cls = getattr(harness, name)
        assert issubclass(cls, Exception)


def test_harness_module_exports_literal_types():
    assert hasattr(harness, "ReturnMode")
    assert hasattr(harness, "RetrieveScope")


# -- import in subprocess (proves no circular imports at module level) ----


def test_harness_imports_cleanly_in_subprocess(tmp_path):
    """Run `python -c "from harness import dispatch"` in a fresh subprocess."""
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c",
         "from harness import dispatch, retrieve, budget_status, DispatchResult; "
         "print('ok')"],
        cwd=repo, capture_output=True, text=True, timeout=30,
        env={**__import__("os").environ, "PYTHONPATH": str(repo / "src")},
    )
    assert result.returncode == 0, (
        f"import failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ok" in result.stdout


# -- function signatures ------------------------------------------------


def test_dispatch_signature_matches_contract():
    """Signature parameter set + defaults must match the W11 spec."""
    sig = inspect.signature(harness.dispatch)
    params = sig.parameters
    assert "prompt" in params
    assert "engine" in params
    assert "return_mode" in params
    assert params["return_mode"].default == "summary"
    assert "timeout_sec" in params
    assert "with_full_text" in params
    assert params["with_full_text"].default is False
    assert "no_cache" in params
    assert params["no_cache"].default is False


def test_retrieve_signature_matches_contract():
    sig = inspect.signature(harness.retrieve)
    params = sig.parameters
    assert "dispatch_id" in params
    assert "scope" in params
    assert params["scope"].default == "summary"
    assert "chunk_size_tokens" in params
    assert params["chunk_size_tokens"].default == 2000


def test_budget_status_signature_matches_contract():
    sig = inspect.signature(harness.budget_status)
    # No required positional args
    assert all(p.default is not inspect.Parameter.empty
               for p in sig.parameters.values())


# -- DispatchResult shape -----------------------------------------------


def test_dispatch_result_has_all_required_fields():
    """The new context-frugal fields per W11-CONTEXT-FRUGAL-RETURN-SCHEMA."""
    required = {
        "success", "engine_used", "dispatch_id",
        "summary", "truncated", "error_excerpt", "content_ref",
        "text", "tokens_in", "tokens_out", "cost_usd", "fallback_chain",
    }
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(harness.DispatchResult)}
    missing = required - field_names
    assert not missing, f"DispatchResult missing fields: {missing}"


def test_dispatch_result_default_is_context_frugal():
    """Defaults: text=None (not full), truncated=True (full text exists
    elsewhere), summary='' (will be populated by impl)."""
    r = harness.DispatchResult(
        success=True, engine_used="kimi", dispatch_id="abc",
    )
    assert r.text is None, "default text MUST be None (context-frugal)"
    assert r.truncated is True
    assert r.summary == ""


def test_dispatch_result_full_method_exists_and_raises_stub():
    """The .full() lazy-fetch method is the stub awaiting Wave 11-D."""
    r = harness.DispatchResult(
        success=True, engine_used="kimi", dispatch_id="abc",
    )
    with pytest.raises(NotImplementedError, match="W11-PYTHON-SDK-API-IMPL"):
        r.full()


# -- Stubs raise NotImplementedError pointing at the impl row ----------


def test_dispatch_stub_raises_notimplemented_with_pointer():
    with pytest.raises(NotImplementedError) as exc_info:
        harness.dispatch("test prompt")
    # Stub message must point at the row that will implement it
    assert "W11-PYTHON-SDK-API-IMPL" in str(exc_info.value) or \
           "Wave 11-D" in str(exc_info.value)


def test_retrieve_implemented_raises_result_not_found_on_missing_id(tmp_path):
    """W11-RETRIEVE-API 2026-05-25: retrieve() now IMPLEMENTED.
    Replaces the prior stub-raises-NotImplementedError test."""
    with pytest.raises(harness.ResultNotFoundError):
        harness.retrieve("never-existed", project_root=str(tmp_path))


def test_budget_status_stub_raises_notimplemented_with_pointer():
    with pytest.raises(NotImplementedError) as exc_info:
        harness.budget_status()
    assert "W11-AGENT-TELEMETRY" in str(exc_info.value) or \
           "W11-PYTHON-SDK-API-IMPL" in str(exc_info.value)


# -- Type stub file exists + parses --------------------------------------


def test_pyi_stub_file_exists():
    repo = Path(__file__).resolve().parents[1]
    stub = repo / "src" / "harness" / "__init__.pyi"
    assert stub.exists(), "harness/__init__.pyi must exist for IDE/agent autocomplete"


def test_pyi_stub_parses_as_python():
    """Type stub file must be syntactically valid Python."""
    import ast
    repo = Path(__file__).resolve().parents[1]
    stub = repo / "src" / "harness" / "__init__.pyi"
    text = stub.read_text(encoding="utf-8")
    # Must parse without SyntaxError
    ast.parse(text)


def test_pyi_stub_declares_dispatch():
    repo = Path(__file__).resolve().parents[1]
    stub = repo / "src" / "harness" / "__init__.pyi"
    text = stub.read_text(encoding="utf-8")
    assert "def dispatch(" in text
    assert "def retrieve(" in text
    assert "def budget_status(" in text
    assert "DispatchResult" in text


# -- HarnessSDKError chain ----------------------------------------------


def test_exception_hierarchy():
    assert issubclass(harness.ResultNotFoundError, harness.HarnessSDKError)
    assert issubclass(harness.ResultCorruptedError, harness.HarnessSDKError)
    assert issubclass(harness.HarnessSDKError, Exception)
