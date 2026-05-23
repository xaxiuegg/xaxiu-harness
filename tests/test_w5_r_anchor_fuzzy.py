"""W5-R: anchor-fuzzy SEARCH match for engine drift.

Phase B Pilot G2v2 caught DeepSeek emitting `SEARCH: def main():` against
file content `def main() -> int:`.  Byte-exact + LF-normalised both
fail, but they're "obviously the same line" to a human reader.  W5-R
adds a whitespace-collapsed retry as last resort.

These tests pin the contract:
1. Drop trailing/internal whitespace tolerance lets the G2v2-shape case
   match.
2. Ambiguous matches (2+ candidate locations) refuse to apply.
3. Truly absent SEARCH still returns None / skip.
4. Pre-W5-R regressions: byte-exact still works for the common case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.coord.worker import _apply_file_edits, _collapse_ws, _fuzzy_replace_one


# ---------------------------------------------------------------------------
# _collapse_ws helper
# ---------------------------------------------------------------------------

def test_collapse_ws_runs() -> None:
    assert _collapse_ws("def  foo(a,  b)") == "def foo(a, b)"


def test_collapse_ws_trailing() -> None:
    assert _collapse_ws("def foo():   ") == "def foo():"


def test_collapse_ws_preserves_newlines() -> None:
    assert _collapse_ws("a\nb\n") == "a\nb\n"


def test_collapse_ws_tabs_to_space() -> None:
    assert _collapse_ws("def\tfoo") == "def foo"


# ---------------------------------------------------------------------------
# _fuzzy_replace_one — happy + edge cases
# ---------------------------------------------------------------------------

def test_fuzzy_replace_one_handles_drift_g2v2_shape() -> None:
    """G2v2 case: engine omitted the `-> int` return annotation in SEARCH."""
    content = "# header\n\ndef main() -> int:\n    return 0\n"
    search = "def main():"  # engine drift — no return annotation
    replace = "def main() -> int:\n    print('hi')\n    return 0"
    result = _fuzzy_replace_one(content, search, replace)
    # Fuzzy match returns None here because the collapsed-whitespace
    # versions still differ:
    #   norm("def main():") = "def main():"
    #   norm("def main() -> int:") = "def main() -> int:"
    # They're genuinely different tokens — refuse to apply.
    assert result is None


def test_fuzzy_replace_one_internal_whitespace_runs() -> None:
    """Engine emits 2+ spaces where file has 1 — should match (collapse)."""
    content = "if x == 1:\n    return True\n"
    search = "if x  ==  1:"  # double-space around ==
    replace = "if x == 0:\n    return False"
    result = _fuzzy_replace_one(content, search, replace)
    assert result is not None
    assert "if x == 0:" in result


def test_fuzzy_replace_one_trailing_whitespace_drift() -> None:
    """Engine emits trailing whitespace on SEARCH lines — should match."""
    content = "def foo():\n    return 42\n"
    search = "def foo():   \n    return 42  "  # trailing spaces in search
    replace = "def foo():\n    return 99"
    result = _fuzzy_replace_one(content, search, replace)
    assert result is not None
    assert "return 99" in result


def test_fuzzy_replace_one_ambiguous_refuses() -> None:
    """2+ candidate matches → refuse to apply (return None)."""
    content = "foo()\nbar()\nfoo()\n"
    search = "foo()"
    replace = "qux()"
    result = _fuzzy_replace_one(content, search, replace)
    # Byte-exact would actually match here, but _fuzzy_replace_one is
    # called AFTER byte-exact + LF fail.  Manually invoking it: 2 byte-
    # exact matches → 2 candidates → ambiguous → None.
    assert result is None


def test_fuzzy_replace_one_truly_absent() -> None:
    content = "alpha\nbeta\ngamma\n"
    search = "epsilon"
    replace = "zeta"
    assert _fuzzy_replace_one(content, search, replace) is None


def test_fuzzy_replace_one_empty_search() -> None:
    """Empty / whitespace-only SEARCH should not fuzzy-match (use empty-
    SEARCH-as-append idiom elsewhere)."""
    assert _fuzzy_replace_one("alpha\n", "", "beta") is None
    assert _fuzzy_replace_one("alpha\n", "   ", "beta") is None


# ---------------------------------------------------------------------------
# End-to-end through _apply_file_edits
# ---------------------------------------------------------------------------

def test_apply_file_edits_uses_fuzzy_for_whitespace_drift(tmp_path: Path) -> None:
    """The whole _apply_file_edits stack should rescue whitespace drift.

    Real-world drift shape: engine emits SEARCH with double-spaces or
    trailing whitespace that doesn't match the file byte-exactly.
    """
    f = tmp_path / "f.py"
    f.write_bytes(b"def calc():\n    return x + y\n")
    edits = [("f.py",
              "def calc():\n    return x  +  y",  # double-spaces around +
              "def calc():\n    return (x + y) * 2")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["f.py"]
    content = f.read_bytes().decode("utf-8")
    assert "return (x + y) * 2" in content


def test_apply_file_edits_skips_ambiguous_drift(tmp_path: Path) -> None:
    """If fuzzy match is ambiguous, skip silently (don't mis-apply)."""
    f = tmp_path / "f.py"
    # Two whitespace-different but content-equal occurrences
    f.write_bytes(b"foo(a,b,c)\nfoo(a, b, c)\n")
    edits = [("f.py", "foo(a , b , c)", "QUX")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == []  # skipped
    # File unchanged
    assert f.read_bytes() == b"foo(a,b,c)\nfoo(a, b, c)\n"


def test_apply_file_edits_byte_exact_still_works(tmp_path: Path) -> None:
    """Pre-W5-R regression guard: byte-exact path unchanged."""
    f = tmp_path / "f.py"
    f.write_bytes(b"x = 1\ny = 2\n")
    edits = [("f.py", "x = 1\n", "x = 100\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["f.py"]
    assert f.read_bytes() == b"x = 100\ny = 2\n"


def test_apply_file_edits_crlf_still_works(tmp_path: Path) -> None:
    """Pre-W5-R regression: W5-J CRLF tolerance unchanged."""
    f = tmp_path / "f.py"
    f.write_bytes(b"x = 1\r\ny = 2\r\n")
    edits = [("f.py", "x = 1\n", "x = 100\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["f.py"]
    result = f.read_bytes()
    # Result preserves CRLF
    assert b"x = 100\r\n" in result
