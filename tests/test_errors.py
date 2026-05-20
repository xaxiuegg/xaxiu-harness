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
