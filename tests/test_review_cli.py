"""W12-B-INSTANT-REVIEW: tests for harness.review module + CLI.

Mocks the engine layer so tests don't hit live engines.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# -- text extraction --------------------------------------------------------


def test_extract_text_reads_markdown(tmp_path: Path) -> None:
    from harness.reviewer import extract_text
    p = tmp_path / "doc.md"
    p.write_text("# hello\n\nworld\n", encoding="utf-8")
    assert "hello" in extract_text(p)
    assert "world" in extract_text(p)


def test_extract_text_reads_py(tmp_path: Path) -> None:
    from harness.reviewer import extract_text
    p = tmp_path / "script.py"
    p.write_text("def foo():\n    return 42\n", encoding="utf-8")
    assert "def foo" in extract_text(p)


def test_extract_text_missing_raises(tmp_path: Path) -> None:
    from harness.reviewer import extract_text
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "nope.md")


def test_extract_text_unsupported_raises_with_hint(tmp_path: Path) -> None:
    from harness.reviewer import extract_text
    p = tmp_path / "thing.docx"
    p.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match="unsupported file type"):
        extract_text(p)


# -- lenses + dispatch ------------------------------------------------------


def _stub_engine(success: bool = True, text: str = "test review output",
                  tokens_in: int = 100, tokens_out: int = 50,
                  cost_usd: float = 0.0, error: str = "") -> object:
    """Return a mock engine that mimics the harness.engines.concrete API."""
    resp = MagicMock()
    resp.success = success
    resp.text = text if success else ""
    resp.tokens_in = tokens_in
    resp.tokens_out = tokens_out
    resp.cost_usd = cost_usd
    resp.error = error
    eng = MagicMock()
    eng.dispatch.return_value = resp
    return eng


def test_review_document_writes_per_engine_files(tmp_path, monkeypatch):
    from harness import reviewer as review

    monkeypatch.setattr(review, "get_engine", lambda *a, **k: _stub_engine())

    doc = tmp_path / "doc.md"
    doc.write_text("# project\n\nsome content\n", encoding="utf-8")
    out = tmp_path / "out"
    result = review.review_document(
        document_path=doc, out_dir=out, max_concurrent=2,
    )
    # 3 default lenses
    assert len(result["results"]) == 3
    assert all(r.ok for r in result["results"])
    # Per-engine files exist
    files = list(out.glob("*.md"))
    assert len(files) >= 3 + 1  # 3 lenses + SYNTHESIS.md


def test_review_document_writes_synthesis(tmp_path, monkeypatch):
    from harness import reviewer as review

    monkeypatch.setattr(review, "get_engine", lambda *a, **k: _stub_engine())
    doc = tmp_path / "doc.md"
    doc.write_text("test content", encoding="utf-8")
    out = tmp_path / "out"
    result = review.review_document(document_path=doc, out_dir=out)
    syn = result["synthesis_path"]
    assert syn.exists()
    text = syn.read_text(encoding="utf-8")
    assert "Multi-engine review" in text
    assert "Per-lens reviews" in text
    assert "test review output" in text  # stub engine output included


def test_review_document_handles_engine_failure(tmp_path, monkeypatch):
    """One lens failing must not crash the whole review."""
    from harness import reviewer as review

    call_count = {"n": 0}

    def _eng(*a, **k):
        call_count["n"] += 1
        return _stub_engine(
            success=(call_count["n"] != 2),  # second lens fails
            error="engine returned empty" if call_count["n"] == 2 else "",
        )

    monkeypatch.setattr(review, "get_engine", _eng)
    doc = tmp_path / "doc.md"
    doc.write_text("content", encoding="utf-8")
    out = tmp_path / "out"
    result = review.review_document(document_path=doc, out_dir=out,
                                     max_concurrent=1)
    n_ok = sum(1 for r in result["results"] if r.ok)
    n_fail = sum(1 for r in result["results"] if not r.ok)
    assert n_ok == 2
    assert n_fail == 1


def test_review_document_respects_max_tokens(tmp_path, monkeypatch):
    """max_tokens must flow through to the engine.dispatch call."""
    from harness import reviewer as review

    captured: list[dict] = []

    def _eng(*a, **k):
        eng = MagicMock()

        def _dispatch(prompt, model, opts):
            captured.append(opts)
            resp = MagicMock()
            resp.success = True
            resp.text = "ok"
            resp.tokens_in = 10
            resp.tokens_out = 5
            resp.cost_usd = 0.0
            return resp
        eng.dispatch.side_effect = _dispatch
        return eng

    monkeypatch.setattr(review, "get_engine", _eng)
    doc = tmp_path / "doc.md"
    doc.write_text("content", encoding="utf-8")
    out = tmp_path / "out"
    review.review_document(document_path=doc, out_dir=out, max_tokens=7777)
    # Each lens's dispatch call carried max_tokens=7777
    for opts in captured:
        assert opts["max_tokens"] == 7777


# -- CLI -------------------------------------------------------------------








def test_cli_review_missing_file_exits_nonzero(tmp_path):
    from click.testing import CliRunner
    from harness.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["review", str(tmp_path / "nope.md")])
    assert result.exit_code != 0


def test_default_lens_set_has_3_engines():
    """The default lens set must dispatch to all 3 production engines."""
    from harness.reviewer import DEFAULT_LENSES
    engines = {lens.engine for lens in DEFAULT_LENSES}
    assert engines == {"kimi", "deepseek", "mimo"}


def test_all_lens_sets_have_valid_engine_names():
    """No typos in engine names across the lens sets."""
    from harness.reviewer import LENS_SETS
    valid_engines = {"kimi", "deepseek", "mimo", "anthropic", "gemini"}
    for set_name, lenses in LENS_SETS.items():
        for lens in lenses:
            assert lens.engine in valid_engines, (
                f"lens-set {set_name!r} lens {lens.id!r} uses unknown "
                f"engine {lens.engine!r}"
            )
