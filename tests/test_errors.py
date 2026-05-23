"""Tests for ``src.harness.errors``."""

from __future__ import annotations

import pytest

from harness.errors import (
    ALLOWED_DOMAINS,
    ALLOWED_LEVELS,
    AllEnginesUnreachable,
    ConfigCorruption,
    DispatchExhausted,
    DpapiUnreadable,
    EngineRefusal,
    EngineTimeout,
    GitPushFailed,
    HarnessError,
    PacketTrap,
    SchemaViolation,
    WavePersistentlyFailing,
    format_escalation_banner,
    handle_harness_error,
)


# ---------------------------------------------------------------------------
# tag formatting
# ---------------------------------------------------------------------------

def test_tag_format_matches_spec() -> None:
    err = DispatchExhausted("all engines failed")
    assert err.tag() == "L3.dispatch.E_DISPATCH_EXHAUSTED"


@pytest.mark.parametrize(
    "cls,expected_tag",
    [
        (DispatchExhausted, "L3.dispatch.E_DISPATCH_EXHAUSTED"),
        (EngineTimeout, "L3.engines.E_ENGINE_TIMEOUT"),
        (EngineRefusal, "L3.engines.E_ENGINE_REFUSAL"),
        (PacketTrap, "L4.engines.E_PACKET_TRAP"),
        (SchemaViolation, "L4.schema.E_SCHEMA_VIOLATION"),
        (DpapiUnreadable, "L5.secrets.E_DPAPI_UNREADABLE"),
        (AllEnginesUnreachable, "L5.network.E_ALL_ENGINES_UNREACHABLE"),
        (GitPushFailed, "L5.network.E_PUSH_FAILED"),
        (ConfigCorruption, "L5.config.E_CONFIG_CORRUPTION"),
        (WavePersistentlyFailing, "L5.dispatch.E_WAVE_PERSISTENTLY_FAILING"),
    ],
)
def test_all_subclass_tags(cls: type[HarnessError], expected_tag: str) -> None:
    err = cls("msg")
    assert err.tag() == expected_tag
    assert err.level in ALLOWED_LEVELS
    assert err.domain in ALLOWED_DOMAINS
    assert err.code.startswith("E_")


# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls,expected_exit",
    [
        (DispatchExhausted, 1),    # L3 -> 1
        (PacketTrap, 3),           # L4 -> 3
        (DpapiUnreadable, 4),      # L5 -> 4
    ],
)
def test_exit_code_mapping(cls: type[HarnessError], expected_exit: int) -> None:
    assert cls("msg").exit_code() == expected_exit


# ---------------------------------------------------------------------------
# to_dict shape (used by jsonl logging in Wave A.6)
# ---------------------------------------------------------------------------

def test_to_dict_has_required_keys() -> None:
    err = SchemaViolation("unknown field 'foo'", context={"file": "state.json"})
    d = err.to_dict()
    assert set(d.keys()) == {"tag", "level", "domain", "code", "message", "context"}
    assert d["tag"] == "L4.schema.E_SCHEMA_VIOLATION"
    assert d["level"] == 4
    assert d["domain"] == "schema"
    assert d["code"] == "E_SCHEMA_VIOLATION"
    assert d["message"] == "unknown field 'foo'"
    assert d["context"] == {"file": "state.json"}


def test_to_dict_no_context_returns_empty_dict() -> None:
    err = DispatchExhausted("nothing left to try")
    d = err.to_dict()
    assert d["context"] == {}


# ---------------------------------------------------------------------------
# validation: subclasses with invalid level/domain/code should fail at instantiation
# ---------------------------------------------------------------------------

class _BadLevelError(HarnessError):
    level = 99
    domain = "config"
    code = "E_BAD"


class _BadDomainError(HarnessError):
    level = 3
    domain = "imaginary"
    code = "E_BAD"


class _BadCodeError(HarnessError):
    level = 3
    domain = "config"
    code = "MISSING_PREFIX"


def test_invalid_level_raises() -> None:
    with pytest.raises(ValueError, match="invalid level"):
        _BadLevelError("oops")


def test_invalid_domain_raises() -> None:
    with pytest.raises(ValueError, match="invalid domain"):
        _BadDomainError("oops")


def test_invalid_code_raises() -> None:
    with pytest.raises(ValueError, match="must start with 'E_'"):
        _BadCodeError("oops")


# ---------------------------------------------------------------------------
# inheritance: HarnessError is a real Exception
# ---------------------------------------------------------------------------

def test_can_be_raised_and_caught() -> None:
    with pytest.raises(HarnessError) as ei:
        raise DispatchExhausted("test")
    assert isinstance(ei.value, DispatchExhausted)
    assert str(ei.value) == "test"


def test_repr_includes_tag() -> None:
    err = DispatchExhausted("test")
    r = repr(err)
    assert "DispatchExhausted" in r
    assert "L3.dispatch.E_DISPATCH_EXHAUSTED" in r


# ---------------------------------------------------------------------------
# W5-Y operator-escalation contract (handle_harness_error / banner)
# ---------------------------------------------------------------------------

def test_l5_banner_contains_escalation_marker() -> None:
    """L5 errors render the operator-escalation banner with a stable
    grep-able marker.  Observer scrapers depend on this exact string."""
    err = ConfigCorruption("state.json is mangled")
    banner = format_escalation_banner(err)
    assert "*** OPERATOR ESCALATION (L5) ***" in banner
    assert "L5.config.E_CONFIG_CORRUPTION" in banner
    assert "state.json is mangled" in banner


def test_l3_summary_has_no_banner() -> None:
    """L3 returns a single-line summary, NOT the L5 escalation banner.
    Autonomous-loop handlers grep for the L5 marker to decide whether
    to halt — L1-L4 must not trigger that path."""
    err = DispatchExhausted("retry exhausted")
    summary = format_escalation_banner(err)
    assert "OPERATOR ESCALATION" not in summary
    assert "[L3.dispatch.E_DISPATCH_EXHAUSTED]" in summary
    assert "retry exhausted" in summary


def test_handle_harness_error_writes_and_returns_code() -> None:
    """handle_harness_error() writes the banner to the given writer
    and returns the exit code, without calling sys.exit by default."""
    written: list[str] = []

    def _writer(s: str) -> int:
        written.append(s)
        return len(s)

    err = AllEnginesUnreachable("no engines reachable")
    code = handle_harness_error(err, stderr_writer=_writer)
    assert code == 4  # L5 exit code
    assert any("OPERATOR ESCALATION (L5)" in w for w in written)


def test_handle_harness_error_invokes_sys_exit_when_provided() -> None:
    """When sys_exit is supplied, the helper terminates after writing."""
    written: list[str] = []
    exit_codes: list[int] = []
    err = DpapiUnreadable("DPAPI fail")
    handle_harness_error(
        err,
        stderr_writer=lambda s: written.append(s) or len(s),
        sys_exit=lambda c: exit_codes.append(c),
    )
    assert exit_codes == [4]
    assert any("OPERATOR ESCALATION" in w for w in written)


def test_handle_l3_does_not_trigger_escalation_marker() -> None:
    """L3 routes through handle_harness_error() but the banner is the
    short summary — exit code 1, no escalation marker."""
    written: list[str] = []
    err = EngineTimeout("read timeout 600s")
    code = handle_harness_error(
        err, stderr_writer=lambda s: written.append(s) or len(s),
    )
    assert code == 1
    assert not any("OPERATOR ESCALATION" in w for w in written)
    assert any("L3.engines.E_ENGINE_TIMEOUT" in w for w in written)


# ---------------------------------------------------------------------------
# W5-DD top-level CLI HarnessError handler
# ---------------------------------------------------------------------------

def test_cli_main_wraps_harness_error_with_escalation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """W5-DD: when a CLI verb raises an unhandled HarnessError, the
    top-level main() wrapper catches it, fires the L5 banner, and exits
    with the level-derived code (4 for L5).  Without the wrapper, click
    would emit a vanilla Python traceback and exit 1."""
    import sys as _sys
    import harness.cli as _cli

    # Make `cli` raise an L5 HarnessError unconditionally.
    def _boom(*args, **kwargs):
        raise ConfigCorruption("simulated bad state.json")

    exit_codes: list[int] = []
    monkeypatch.setattr(_cli, "cli", _boom)
    monkeypatch.setattr(_sys, "exit", lambda c=0: exit_codes.append(c))

    _cli.main()

    captured = capsys.readouterr()
    assert "*** OPERATOR ESCALATION (L5) ***" in captured.err
    assert "L5.config.E_CONFIG_CORRUPTION" in captured.err
    assert exit_codes == [4]


def test_cli_main_does_not_intercept_non_harness_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5-DD: only HarnessError subclasses route through the wrapper.
    Generic exceptions (ValueError, RuntimeError, etc.) propagate
    untouched so the standard click traceback path still works."""
    import harness.cli as _cli

    def _boom(*args, **kwargs):
        raise RuntimeError("not a HarnessError")

    monkeypatch.setattr(_cli, "cli", _boom)
    with pytest.raises(RuntimeError, match="not a HarnessError"):
        _cli.main()
