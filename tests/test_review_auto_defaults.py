"""W13 Tier 1 Shifts A + F: auto-pick lens-set + safe-floor max_tokens.

Two narrow behaviors with strong contracts:

- infer_lens_set(path): file extension picks "code-review" /
  "doc-review" / "default" so agents calling ``harness.review()``
  don't need to learn the lens-set vocab before getting useful output.

- auto_max_tokens(quick=, override=): safe floor 4000 by default, 1000
  for --quick, explicit override always wins.  Caught the 2000-default
  truncation regression noted in the master audit + the operator's
  2026-05-24 high-cap directive.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.reviewer import (
    QUICK_MAX_TOKENS,
    SAFE_MAX_TOKENS_FLOOR,
    auto_max_tokens,
    infer_lens_set,
)


class TestInferLensSet:
    """File extension -> lens-set name."""

    @pytest.mark.parametrize("path,expected", [
        ("src/foo/parser.py", "code-review"),
        ("ui/app.js", "code-review"),
        ("ui/app.ts", "code-review"),
        ("ui/component.tsx", "code-review"),
        ("server/main.go", "code-review"),
        ("server/main.rs", "code-review"),
        ("App.java", "code-review"),
        ("util.cpp", "code-review"),
        ("script.sh", "code-review"),
        ("script.ps1", "code-review"),
        ("query.sql", "code-review"),
    ])
    def test_code_suffix_picks_code_review(self, path, expected):
        assert infer_lens_set(path) == expected
        assert infer_lens_set(Path(path)) == expected

    @pytest.mark.parametrize("path,expected", [
        ("docs/AGENT_QUICKSTART.md", "doc-review"),
        ("README.markdown", "doc-review"),
        ("notes.txt", "doc-review"),
        ("paper.pdf", "doc-review"),
        ("manual.rst", "doc-review"),
        ("page.html", "doc-review"),
        ("page.htm", "doc-review"),
    ])
    def test_doc_suffix_picks_doc_review(self, path, expected):
        assert infer_lens_set(path) == expected

    @pytest.mark.parametrize("path", [
        "data.csv",  # data, not code or doc
        "config.yaml",  # config, ambiguous
        "image.png",  # binary
        "no-extension",
        "archive.tar.gz",  # weird tarball
        "weird.xyzunknown",
    ])
    def test_unknown_suffix_picks_default(self, path):
        assert infer_lens_set(path) == "default"

    def test_case_insensitive(self):
        # The implementation lowercases suffix; uppercase should still match
        assert infer_lens_set("FOO.PY") == "code-review"
        assert infer_lens_set("DOC.MD") == "doc-review"


class TestAutoMaxTokens:
    """Safe-floor max_tokens with --quick opt-down + explicit override."""

    def test_default_returns_safe_floor(self):
        assert auto_max_tokens() == SAFE_MAX_TOKENS_FLOOR
        assert SAFE_MAX_TOKENS_FLOOR == 4000  # contract constant

    def test_quick_returns_quick_value(self):
        assert auto_max_tokens(quick=True) == QUICK_MAX_TOKENS
        assert QUICK_MAX_TOKENS == 1000  # contract constant

    def test_override_wins_over_quick(self):
        # Explicit number always wins, even with quick=True
        assert auto_max_tokens(quick=True, override=8000) == 8000

    def test_override_wins_over_default(self):
        assert auto_max_tokens(override=12000) == 12000

    def test_override_below_floor_still_honored(self):
        # Explicit choice is the operator's; we don't silently bump it.
        # The safe floor only applies to the AUTO-pick path.
        assert auto_max_tokens(override=500) == 500

    def test_override_zero_returns_zero(self):
        # Operator can deliberately set 0 (engine will reject; not our job)
        assert auto_max_tokens(override=0) == 0

    def test_quick_false_explicit(self):
        assert auto_max_tokens(quick=False) == SAFE_MAX_TOKENS_FLOOR


class TestSafeFloorContract:
    """Floor + quick constants must remain stable (panel-approved values)."""

    def test_safe_floor_is_at_least_4000(self):
        # The W13 panel verdict: never silently below 4000 for reviews
        assert SAFE_MAX_TOKENS_FLOOR >= 4000

    def test_quick_is_well_below_floor(self):
        # Quick mode is deliberately a fast preview; should be < floor
        assert QUICK_MAX_TOKENS < SAFE_MAX_TOKENS_FLOOR
        assert QUICK_MAX_TOKENS >= 256  # but not absurdly low
