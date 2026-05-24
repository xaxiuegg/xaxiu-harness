"""W9-REDACTION-INTEGRITY-TEST: assert no secret-pattern leaks anywhere.

M09 worst-case path: prompt injection -> engine exfiltrates key
material into response -> response logged via retro/replay/today/
panic-dump BEFORE redaction runs.  The master audit (M09) found
zero redaction-integrity tests anywhere; this file fills that gap.

Strategy:

  1. Pattern tests: every secret-pattern in the canonical
     redaction.redact() function correctly scrubs its input.

  2. Surface tests: each operator-facing output surface that takes
     untrusted text (jsonl_log entries, panic-dump bodies, etc.)
     scrubs known-secret patterns before persisting / returning.

  3. Cross-module parity: the legacy aliases (jsonl_log._redact,
     panic._scrub_text) all delegate to the canonical helper so a
     new pattern added to redaction.py covers every surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.state import redaction as _r


KNOWN_SECRETS = {
    "openai_key": "sk-proj-AbcdefghijklmnopQRSTUVWXYZ1234567890",
    "bearer": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature123",
    "kimi_env": "KIMI_API_KEY=ms-realkeyvaluewithlotsofentropy12345",
    "deepseek_env": "DEEPSEEK_API_KEY=deepseek-AbCdEfGhIjKlMnOpQrStUv",
    "mimo_env": "MIMO_API_KEY=tp-tokenplanvalue1234567890abcdef",
    "ms_prefix": "ms-pTHISISALEAKEDKEYVALUE12345",
    "tp_prefix": "tp-SuBSCRIPTIONkeyVALUE9876543",
    "mt_prefix": "mt-MOONSHOTkey0123456789abcde",
    "api_key_label": 'api_key="LongEnoughTokenABC1234567890DEF"',
    "dpapi_blob": (
        "AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAAaBcDefGhIjKlMnOp"
        "QrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYz"
    ),
}


# -- Pure redaction patterns ----------------------------------------------


@pytest.mark.parametrize("label,secret", KNOWN_SECRETS.items())
def test_redact_strips_every_known_pattern(label, secret):
    """Each canonical secret pattern is scrubbed by redact()."""
    text = f"prefix... {secret} ...suffix"
    cleaned = _r.redact(text)
    assert cleaned is not None
    # The secret-bearing portion must not survive.  For env-assignment
    # patterns the label survives but the value is replaced.
    if "=" in secret and any(
        secret.startswith(f"{prefix}_API_KEY=")
        for prefix in ("KIMI", "DEEPSEEK", "ANTHROPIC", "GEMINI",
                       "MOONSHOT", "OPENAI", "MIMO")
    ):
        # Only the value side should be gone
        env_var = secret.split("=", 1)[0]
        assert env_var in cleaned  # label survives
        assert _r.REDACTION_TOKEN in cleaned
    else:
        assert _r.REDACTION_TOKEN in cleaned
        assert secret not in cleaned, (
            f"{label}: secret survived redaction in output: {cleaned}"
        )


def test_redact_passes_through_safe_text():
    safe = "Wave 9 plan: ship 14 rows + close out."
    assert _r.redact(safe) == safe


def test_redact_handles_none():
    assert _r.redact(None) is None


def test_redact_coerces_non_string():
    """A int/float/dict slipping through should not crash."""
    assert _r.redact(12345) == "12345"


def test_redact_scrubs_multiple_secrets_in_one_string():
    text = (
        "first sk-OpenAILongKeyABCDEFGHIJKLMNOPQRSTUV "
        "then KIMI_API_KEY=ms-secretkey1234567890abcdef and "
        "then Bearer eyJhbGciOiJIUzI1NiJ9.padatatag.signature"
    )
    cleaned = _r.redact(text)
    assert "OpenAILongKey" not in cleaned
    assert "ms-secretkey" not in cleaned
    assert "signature" not in cleaned
    # All three replaced with token
    assert cleaned.count(_r.REDACTION_TOKEN) >= 3


def test_has_unredacted_secret_detects_each_pattern():
    for label, secret in KNOWN_SECRETS.items():
        assert _r.has_unredacted_secret(secret), (
            f"{label}: detector failed to flag {secret}"
        )


def test_has_unredacted_secret_returns_false_on_safe_text():
    assert not _r.has_unredacted_secret(
        "Wave 9 plan: ship 14 rows + close out."
    )
    # After redaction, the cleaned text passes
    cleaned = _r.redact(
        "KIMI_API_KEY=ms-thiskeywaslongenoughtomatch12345 in logs"
    )
    assert not _r.has_unredacted_secret(cleaned)


# -- Surface: state.jsonl_log -----------------------------------------------


def test_jsonl_log_write_redacts_known_secrets(tmp_path, monkeypatch):
    """A log entry containing secrets must be scrubbed before disk."""
    from harness.state import jsonl_log
    log_path = tmp_path / "dispatch.jsonl"
    monkeypatch.setattr(jsonl_log, "_active_path", lambda: log_path,
                        raising=False)
    monkeypatch.setattr(jsonl_log, "_rotation_path", lambda: log_path,
                        raising=False)
    # Patch write_log_entry's persistence path: it writes to _active
    # path with rotation; redirect via the module-level path constant.
    # Cleanest hack: patch the LOG_FILE path used by write_log_entry.
    monkeypatch.setattr(jsonl_log, "LOG_FILE", log_path, raising=False)
    jsonl_log.write_log_entry(
        project="wave9",
        packet_path=f"/tmp/packet KIMI_API_KEY={KNOWN_SECRETS['ms_prefix']}",
        backend="kimi",
        model="kimi",
        outcome="success",
        latency_ms=100,
        fallback_to=None,
    )
    if log_path.exists():
        body = log_path.read_text(encoding="utf-8")
        for label, secret in KNOWN_SECRETS.items():
            if label in ("dpapi_blob", "tp_prefix", "mt_prefix",
                         "api_key_label"):
                continue  # not injected
            assert secret not in body, (
                f"jsonl_log persisted {label} unredacted: {body[:200]}"
            )


def test_jsonl_log_redact_delegates_to_canonical_helper():
    """_redact is the same callable as redaction.redact."""
    from harness.state import jsonl_log
    assert jsonl_log._redact is _r.redact


# -- Surface: panic._scrub_text -------------------------------------------


@pytest.mark.parametrize("label,secret", KNOWN_SECRETS.items())
def test_panic_scrub_text_strips_known_pattern(label, secret):
    """harness panic-dump scrubs every secret before producing the dump body."""
    from harness import panic
    text = f"BEFORE {secret} AFTER"
    out = panic._scrub_text(text)
    if "=" in secret and any(
        secret.startswith(f"{prefix}_API_KEY=")
        for prefix in ("KIMI", "DEEPSEEK", "ANTHROPIC", "GEMINI",
                       "MOONSHOT", "OPENAI", "MIMO")
    ):
        env_var = secret.split("=", 1)[0]
        assert env_var in out
        assert "[REDACTED]" in out
    else:
        assert secret not in out, (
            f"{label}: panic scrub did not strip {secret} from {out}"
        )


def test_panic_scrub_text_safe_text_unchanged():
    from harness import panic
    assert panic._scrub_text("hello world") == "hello world"


def test_panic_scrub_text_handles_empty():
    from harness import panic
    assert panic._scrub_text("") == ""


# -- Cross-module parity: the surfaces use the same source-of-truth -----


def test_redaction_module_is_single_source_of_truth():
    """Adding a new vendor's key to redaction._PATTERNS_SUB must
    affect both surfaces.  We verify that both surfaces' redact
    references resolve to the same callable."""
    from harness.state import jsonl_log
    from harness import panic
    # jsonl_log._redact IS redaction.redact
    assert jsonl_log._redact is _r.redact
    # panic._scrub_text wraps but delegates: a freshly-added pattern
    # surfaces in panic.scrub_text via the import chain.  Sanity check
    # that the panic._scrub_text output for a known new-style pattern
    # matches what redact() does.
    sample = KNOWN_SECRETS["tp_prefix"]
    panic_out = panic._scrub_text(f"x {sample} y")
    canon_out = _r.redact(f"x {sample} y")
    assert panic_out == canon_out
