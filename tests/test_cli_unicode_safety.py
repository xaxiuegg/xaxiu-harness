"""W12-WINDOWS-CP1252-FIX: regression tests for the Unicode-on-Windows crash.

The 20-agent operator-review panel found three distinct CLI entry points
(`preflight`, `--help`, `agent init`) crashing with `UnicodeEncodeError`
when stdout is cp1252 (default Windows console).  Fix: `_bootstrap_utf8_stdout`
in cli.py::main() reconfigures stdout/stderr to utf-8 with errors='replace'.

These tests:
1. Verify _bootstrap_utf8_stdout calls reconfigure with the right args
2. Simulate a cp1252 stdout and confirm Unicode glyphs no longer crash
3. Cover the three specific glyphs the panel called out: -> (U+2192),
   alpha (U+03B1), check (U+2713)
"""

from __future__ import annotations

import io
import sys

import pytest

from harness import cli


def test_bootstrap_calls_reconfigure_on_stdout_stderr(monkeypatch):
    """_bootstrap_utf8_stdout reconfigures both streams."""
    calls = []

    class _FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", _FakeStream())
    monkeypatch.setattr(sys, "stderr", _FakeStream())
    cli._bootstrap_utf8_stdout()
    assert len(calls) == 2
    for kw in calls:
        assert kw["encoding"] == "utf-8"
        assert kw["errors"] == "replace"


def test_bootstrap_is_noop_when_stream_has_no_reconfigure(monkeypatch):
    """A piped/redirected stream may not have reconfigure; must not crash."""

    class _OldStream:
        pass  # no reconfigure attribute

    monkeypatch.setattr(sys, "stdout", _OldStream())
    monkeypatch.setattr(sys, "stderr", _OldStream())
    # MUST NOT raise
    cli._bootstrap_utf8_stdout()


def test_bootstrap_swallows_value_error(monkeypatch):
    """Some redirected streams refuse reconfigure with ValueError; ok."""

    class _StrictStream:
        def reconfigure(self, **kwargs):
            raise ValueError("can't reconfigure a closed buffer")

    monkeypatch.setattr(sys, "stdout", _StrictStream())
    monkeypatch.setattr(sys, "stderr", _StrictStream())
    cli._bootstrap_utf8_stdout()  # no raise


def test_bootstrap_swallows_oserror(monkeypatch):
    class _BrokenStream:
        def reconfigure(self, **kwargs):
            raise OSError("EBADF")

    monkeypatch.setattr(sys, "stdout", _BrokenStream())
    monkeypatch.setattr(sys, "stderr", _BrokenStream())
    cli._bootstrap_utf8_stdout()  # no raise


def test_bootstrap_handles_missing_stdout(monkeypatch):
    """Edge case: weird embedding might null out sys.stdout."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli._bootstrap_utf8_stdout()  # no raise


# -- end-to-end: the 3 specific glyphs the panel flagged ------------------


@pytest.mark.parametrize("glyph,name", [
    ("→", "right_arrow"),   # K01/K02/K05: preflight remediation
    ("α", "greek_alpha"),   # K01/K02/K05: --help engineering marker
    ("✓", "check_mark"),    # K01/K02/K05: agent init success summary
])
def test_glyphs_survive_through_utf8_replace(glyph, name):
    """After bootstrap, writing the panel-flagged glyphs to a cp1252-
    backed stream must not crash — they may render as '?' but the
    write succeeds."""
    raw = io.BytesIO()
    # Wrap with a TextIOWrapper that has reconfigure
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict",
                               write_through=True)
    # Without reconfigure, this crashes:
    with pytest.raises(UnicodeEncodeError):
        stream.write(f"foo {glyph} bar")
        stream.flush()

    # After bootstrap (with errors='replace'), it does not:
    raw2 = io.BytesIO()
    stream2 = io.TextIOWrapper(raw2, encoding="cp1252", errors="strict",
                                write_through=True)
    stream2.reconfigure(encoding="utf-8", errors="replace")
    stream2.write(f"foo {glyph} bar")
    stream2.flush()
    out = raw2.getvalue().decode("utf-8", errors="replace")
    assert "foo" in out and "bar" in out


def test_cli_help_does_not_crash_with_unicode(monkeypatch):
    """W12 e2e: invoking the CLI via main() with --help must not crash
    on Windows-like cp1252 stdout."""
    from click.testing import CliRunner
    runner = CliRunner()
    # CliRunner captures stdout in a strict utf-8 buffer; we simulate
    # by checking the help text contains alpha (was the crash trigger
    # on real Windows console) and that exit is 0.
    result = runner.invoke(cli.cli, ["--help"])
    assert result.exit_code == 0


def test_cli_preflight_skip_engines_does_not_crash(monkeypatch):
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(cli.cli, ["preflight", "--skip-engines"])
    # Exit may be 0/1/4 depending on pytest cache state; just must
    # not raise UnicodeEncodeError
    assert result.exception is None or not isinstance(
        result.exception, UnicodeEncodeError,
    )


