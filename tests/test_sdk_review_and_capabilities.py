"""W13 Wed-Thu bundle: harness.review() + harness.capabilities() SDK fns.

These are the SDK-facing twins of the CLI verbs.  Agents calling
`harness.review(path)` get the same multi-engine review pipeline the
CLI provides, with auto-defaults from Tier 1 Shifts A + F.

`harness.capabilities()` introspects the install: SDK functions, CLI
verbs, reachable engines, lens-sets, audit ledger settings.  It is the
"what can this thing do" entry point for fresh-clone agents.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# harness.capabilities() — introspection only, no dispatch
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_returns_dict_with_required_top_level_keys(self):
        from harness import capabilities
        cap = capabilities()
        assert isinstance(cap, dict)
        for k in ("version", "python_version", "platform",
                  "sdk_functions", "cli_verbs", "review",
                  "engines", "audit"):
            assert k in cap, f"missing top-level key: {k}"

    def test_version_matches_package_version(self):
        from harness import capabilities, __version__
        cap = capabilities()
        assert cap["version"] == __version__

    def test_python_version_is_real(self):
        from harness import capabilities
        cap = capabilities()
        assert cap["python_version"].startswith(sys.version.split()[0])

    def test_sdk_functions_lists_the_publics(self):
        from harness import capabilities
        cap = capabilities()
        fns = cap["sdk_functions"]
        # The Tier-1 publics must all appear
        for required in ("dispatch", "retrieve", "review",
                         "budget_status", "capabilities"):
            assert required in fns, f"capabilities missing SDK fn: {required}"

    def test_cli_verbs_includes_audit_and_review_and_capabilities(self):
        from harness import capabilities
        cap = capabilities()
        verbs = cap["cli_verbs"]
        for required in ("audit", "review", "capabilities", "dispatch"):
            assert required in verbs, f"capabilities missing CLI verb: {required}"

    def test_review_section_has_lens_sets_and_floor(self):
        from harness import capabilities
        from harness.reviewer import (
            QUICK_MAX_TOKENS, SAFE_MAX_TOKENS_FLOOR,
        )
        cap = capabilities()
        rv = cap["review"]
        assert "lens_sets" in rv
        assert "default" in rv["lens_sets"]
        assert "code-review" in rv["lens_sets"]
        assert "doc-review" in rv["lens_sets"]
        assert rv["default_max_tokens"] == SAFE_MAX_TOKENS_FLOOR
        assert rv["quick_max_tokens"] == QUICK_MAX_TOKENS
        # Common extensions covered
        exts = rv["supported_extensions"]
        for required in (".py", ".md", ".pdf", ".txt"):
            assert required in exts, f"review missing extension: {required}"

    def test_engines_section_has_configured_list(self):
        from harness import capabilities
        cap = capabilities()
        eng = cap["engines"]
        # The 5 known production engines must all be listed
        configured = eng.get("configured", [])
        for e in ("kimi", "deepseek", "mimo", "anthropic", "gemini"):
            assert e in configured, f"capabilities missing engine: {e}"
        # keys_present must be a dict of bool
        kp = eng["keys_present"]
        assert isinstance(kp, dict)
        for e, v in kp.items():
            assert isinstance(v, bool)

    def test_audit_section_has_ledger_path(self):
        from harness import capabilities
        cap = capabilities()
        aud = cap["audit"]
        assert "ledger_path" in aud
        assert "max_age_days" in aud
        assert isinstance(aud["max_age_days"], int)

    def test_capabilities_is_cheap_no_engine_dispatch(self):
        """Must not actually call an engine — pure introspection."""
        # We don't patch get_engine itself because capabilities NEEDS it
        # for key-presence detection — but capabilities must never call
        # .dispatch() on any engine.  Patch the dispatch path instead.
        from harness import capabilities
        with patch("harness.engines.dispatcher.dispatch_packet") as mocked:
            capabilities()
            mocked.assert_not_called()

    def test_json_serializable(self):
        """`capabilities` output must round-trip through JSON for CLI."""
        from harness import capabilities
        cap = capabilities()
        # Should not raise
        s = json.dumps(cap, default=str)
        # And round-trip
        round_trip = json.loads(s)
        assert round_trip["version"] == cap["version"]


# ---------------------------------------------------------------------------
# harness.review() — SDK wrapper around harness.review.review_document
# ---------------------------------------------------------------------------


class TestReviewSDK:
    def _make_fake_lens_result(self, lens):
        from harness.reviewer import LensResult
        return LensResult(
            lens=lens, ok=True,
            text="finding 1\nfinding 2\n",
            elapsed_s=0.5, tokens_in=100, tokens_out=200,
            cost_usd=0.0001,
        )

    def test_review_returns_review_result_dataclass(self, tmp_path):
        from harness import review, ReviewResult
        doc = tmp_path / "sample.md"
        doc.write_text("# A doc\n\nbody\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 42,
                "elapsed_s": 1.5,
                "total_cost_usd": 0.0003,
            }
            r = review(str(doc))
        assert isinstance(r, ReviewResult)
        assert r.elapsed_s == 1.5
        assert r.total_cost_usd == 0.0003
        assert r.document_text_length == 42
        assert r.successful_lenses == 0
        assert r.failed_lenses == 0

    def test_review_auto_picks_lens_set_from_extension(self, tmp_path):
        from harness import review
        doc = tmp_path / "sample.py"
        doc.write_text("def f():\n    pass\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 20,
                "elapsed_s": 1.0,
                "total_cost_usd": 0.0,
            }
            r = review(str(doc))
        # .py -> code-review (per infer_lens_set)
        assert r.lens_set_used == "code-review"
        # The lens-set actually passed to review_document is code-review's
        from harness.reviewer import LENS_SETS
        args, kwargs = mocked.call_args
        assert kwargs["lenses"] is LENS_SETS["code-review"]

    def test_review_auto_picks_max_tokens_safe_floor(self, tmp_path):
        from harness import review
        from harness.reviewer import SAFE_MAX_TOKENS_FLOOR
        doc = tmp_path / "sample.md"
        doc.write_text("body\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 5,
                "elapsed_s": 0.5,
                "total_cost_usd": 0.0,
            }
            r = review(str(doc))
        assert r.max_tokens_used == SAFE_MAX_TOKENS_FLOOR
        _, kwargs = mocked.call_args
        assert kwargs["max_tokens"] == SAFE_MAX_TOKENS_FLOOR

    def test_review_quick_mode_drops_max_tokens(self, tmp_path):
        from harness import review
        from harness.reviewer import QUICK_MAX_TOKENS
        doc = tmp_path / "sample.md"
        doc.write_text("body\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 5,
                "elapsed_s": 0.1,
                "total_cost_usd": 0.0,
            }
            r = review(str(doc), quick=True)
        assert r.max_tokens_used == QUICK_MAX_TOKENS

    def test_review_explicit_max_tokens_wins(self, tmp_path):
        from harness import review
        doc = tmp_path / "sample.md"
        doc.write_text("body\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 5,
                "elapsed_s": 0.1,
                "total_cost_usd": 0.0,
            }
            r = review(str(doc), max_tokens=12000, quick=True)
        # Explicit override beats --quick
        assert r.max_tokens_used == 12000

    def test_review_explicit_lens_set_wins(self, tmp_path):
        from harness import review
        doc = tmp_path / "sample.py"  # would auto -> code-review
        doc.write_text("pass\n", encoding="utf-8")
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": [],
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 5,
                "elapsed_s": 0.1,
                "total_cost_usd": 0.0,
            }
            r = review(str(doc), lens_set="default")
        # Explicit override beats inference
        assert r.lens_set_used == "default"

    def test_review_unknown_lens_set_raises(self, tmp_path):
        from harness import review
        doc = tmp_path / "sample.md"
        doc.write_text("body\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown lens_set"):
            review(str(doc), lens_set="not-a-real-set")

    def test_review_propagates_lens_results(self, tmp_path):
        from harness import review
        from harness.reviewer import DEFAULT_LENSES
        doc = tmp_path / "sample.md"
        doc.write_text("body\n", encoding="utf-8")
        fake_results = [self._make_fake_lens_result(L) for L in DEFAULT_LENSES]
        with patch("harness.reviewer.review_document") as mocked:
            mocked.return_value = {
                "results": fake_results,
                "out_dir": tmp_path / "out",
                "synthesis_path": tmp_path / "out" / "SYNTHESIS.md",
                "document_text_length": 5,
                "elapsed_s": 1.0,
                "total_cost_usd": 0.0003,
            }
            r = review(str(doc))
        assert r.successful_lenses == 3
        assert r.failed_lenses == 0
        assert len(r.lens_results) == 3
        for lr in r.lens_results:
            assert lr["ok"] is True
            assert lr["error"] is None
            assert isinstance(lr["tokens_in"], int)
