"""W5-J: CRLF-tolerant FILE/REPLACE application.

Engines emit \\n line endings.  Windows files often have \\r\\n.
Byte-exact `search in content` fails when the file is CRLF and the
engine's SEARCH is LF, even when the text is semantically identical.

Path 2 pilot caught this on CHANGELOG.md: DeepSeek v4-pro produced a
perfectly valid FILE/REPLACE block but byte-exact match failed,
triggering W4-A silent_no_op.  W5-J adds normalised retry.

This test pins the contract:
1. Byte-exact match still works (no regression on LF files)
2. CRLF files with LF SEARCH match in normalised space
3. Re-emit preserves the file's original line ending convention
4. SEARCH that's truly absent (not just line-ending diff) is skipped
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.coord.worker import _apply_file_edits


def test_byte_exact_match_lf_file(tmp_path: Path) -> None:
    """Pre-W5-J regression: LF file + LF SEARCH still works."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"# title\n\noriginal line\nfooter\n")
    edits = [("doc.md", "original line\n", "new line\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["doc.md"]
    assert f.read_bytes() == b"# title\n\nnew line\nfooter\n"


def test_crlf_file_lf_search_matches_normalised(tmp_path: Path) -> None:
    """W5-J: CRLF file with LF SEARCH should still match + preserve CRLF."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"# title\r\n\r\noriginal line\r\nfooter\r\n")
    edits = [("doc.md", "original line\n", "new line\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["doc.md"]
    # Output preserves CRLF
    result = f.read_bytes()
    assert b"new line" in result
    # All line endings should be CRLF
    assert result.count(b"\r\n") >= 3  # title, blank, new line, footer
    assert b"\n" not in result.replace(b"\r\n", b"")


def test_truly_absent_search_skipped(tmp_path: Path) -> None:
    """W5-J: if SEARCH text is genuinely not in file (not just line-ending
    diff), skip silently — original behaviour preserved."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"# title\r\n\r\noriginal\r\nfooter\r\n")
    edits = [("doc.md", "totally-different-text\n", "would-not-apply\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == []  # nothing modified
    # File unchanged
    assert f.read_bytes() == b"# title\r\n\r\noriginal\r\nfooter\r\n"


def test_multiline_search_crlf(tmp_path: Path) -> None:
    """W5-J: multi-line SEARCH against CRLF file should match in normalised space."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"# v0.5 \xe2\x80\x94 old\r\n\r\nbody\r\n")
    search = "# v0.5 — old\n\nbody\n"
    replace = "# v0.6 — new\n\nbody\n"
    edits = [("doc.md", search, replace)]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["doc.md"]
    result = f.read_bytes().decode("utf-8")
    assert "v0.6" in result
    assert "v0.5" not in result
    # CRLF preserved
    assert "\r\n" in result


def test_new_file_create_preserves_lf(tmp_path: Path) -> None:
    """When creating a new file (no existing content), use LF (engine's format)."""
    edits = [("new_file.md", "", "fresh content\nline 2\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["new_file.md"]
    # New file: should match engine output verbatim (LF)
    assert (tmp_path / "new_file.md").read_bytes() == b"fresh content\nline 2\n"


def test_empty_search_append_idiom_lf(tmp_path: Path) -> None:
    """Empty SEARCH on existing LF file → append, preserve LF."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"existing\n")
    edits = [("doc.md", "", "appended\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["doc.md"]
    assert f.read_bytes() == b"existing\nappended\n"


def test_empty_search_append_idiom_crlf(tmp_path: Path) -> None:
    """Empty SEARCH on existing CRLF file → append, preserve CRLF."""
    f = tmp_path / "doc.md"
    f.write_bytes(b"existing\r\n")
    edits = [("doc.md", "", "appended\n")]
    modified = _apply_file_edits(edits, tmp_path)
    assert modified == ["doc.md"]
    # Append + line-ending normalisation: appended should be CRLF too
    result = f.read_bytes()
    assert b"existing\r\n" in result
    assert b"appended\r\n" in result
    # No stray LF without preceding CR
    assert b"\n" not in result.replace(b"\r\n", b"")
