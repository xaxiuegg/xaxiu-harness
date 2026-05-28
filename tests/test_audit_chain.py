"""W14-AUDIT-CHAIN-HMAC 2026-05-28: tests for the tamper-evident audit ledger.

Covers:

- canonical JSON encoding stability (HMAC must reproduce byte-for-byte)
- HMAC computation + chain linking
- key resolution priority (env > DPAPI > auto-generate)
- verifier on empty / legacy / chained / mixed ledgers
- tamper detection at hmac field, prev_hash field, and any other field
- chain restart points (file start, post-legacy, post-prune)
- end-to-end integration with append_dispatch_event
- failure modes: missing key, malformed JSON, file read errors

These tests intentionally set ``HARNESS_AUDIT_HMAC_KEY`` via monkeypatch
so they're cross-platform — no DPAPI required.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.audit_chain import (
    CHAIN_FIELDS,
    GENESIS_HASH,
    HMAC_KEY_NAME,
    ChainVerifyResult,
    canonical_json,
    chain_event,
    compute_hmac,
    get_hmac_key,
    get_last_chain_hash,
    verify_chain,
)


# ---------------------------------------------------------------------------
# canonical JSON
# ---------------------------------------------------------------------------


class TestCanonicalJSON:
    """The HMAC's stability hinges on canonical_json being deterministic."""

    def test_sorted_keys(self) -> None:
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_json(a) == canonical_json(b)

    def test_tight_separators(self) -> None:
        out = canonical_json({"a": 1, "b": 2})
        assert b" " not in out  # no spaces in separators
        assert out == b'{"a":1,"b":2}'

    def test_unicode_not_escaped(self) -> None:
        out = canonical_json({"engine": "kimi", "note": "测试"})
        assert "测试".encode("utf-8") in out

    def test_nested(self) -> None:
        out = canonical_json({"x": {"b": 2, "a": 1}})
        assert out == b'{"x":{"a":1,"b":2}}'


# ---------------------------------------------------------------------------
# HMAC + chain
# ---------------------------------------------------------------------------


class TestComputeHmac:
    KEY = b"\x00" * 32  # all-zero test key, intentionally weak

    def test_excludes_hmac_field(self) -> None:
        """The hmac field must not participate in its own computation."""
        e1 = {"engine": "kimi", "ts": "x"}
        e2 = {"engine": "kimi", "ts": "x", "hmac": "anything"}
        assert compute_hmac(e1, self.KEY) == compute_hmac(e2, self.KEY)

    def test_reproducible(self) -> None:
        event = {"engine": "kimi", "tokens_in": 100, "prev_hash": GENESIS_HASH}
        h1 = compute_hmac(event, self.KEY)
        h2 = compute_hmac(event, self.KEY)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_key_changes_hmac(self) -> None:
        event = {"engine": "kimi"}
        h_a = compute_hmac(event, b"key_a" * 8)
        h_b = compute_hmac(event, b"key_b" * 8)
        assert h_a != h_b

    def test_field_change_changes_hmac(self) -> None:
        e1 = {"engine": "kimi", "tokens_in": 100}
        e2 = {"engine": "kimi", "tokens_in": 101}
        assert compute_hmac(e1, self.KEY) != compute_hmac(e2, self.KEY)


class TestChainEvent:
    KEY = b"chain-test-key" * 4

    def test_adds_chain_fields(self) -> None:
        e = {"engine": "kimi", "tokens_in": 50}
        chained = chain_event(e, GENESIS_HASH, self.KEY)
        for field in CHAIN_FIELDS:
            assert field in chained, f"chain_event should add {field}"
        assert chained["prev_hash"] == GENESIS_HASH

    def test_does_not_mutate_input(self) -> None:
        e = {"engine": "kimi"}
        chain_event(e, GENESIS_HASH, self.KEY)
        assert "prev_hash" not in e
        assert "hmac" not in e

    def test_chain_links(self) -> None:
        """Second event's prev_hash should equal the first's hmac."""
        e1 = chain_event({"engine": "kimi"}, GENESIS_HASH, self.KEY)
        e2 = chain_event({"engine": "deepseek"}, e1["hmac"], self.KEY)
        assert e2["prev_hash"] == e1["hmac"]


# ---------------------------------------------------------------------------
# key resolution
# ---------------------------------------------------------------------------


class TestGetHmacKey:
    def test_env_var_hex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hex_key = "ab" * 32  # 64 hex chars = 32 bytes
        monkeypatch.setenv(HMAC_KEY_NAME, hex_key)
        key = get_hmac_key(auto_generate=False)
        assert key == bytes.fromhex(hex_key)

    def test_env_var_raw_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HMAC_KEY_NAME, "not-a-hex-string-zzz")
        key = get_hmac_key(auto_generate=False)
        assert key == b"not-a-hex-string-zzz"

    def test_env_var_short_hex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HMAC_KEY_NAME, "deadbeef")
        key = get_hmac_key(auto_generate=False)
        # 8 hex chars decodes to 4 bytes — accepted as hex
        assert key == bytes.fromhex("deadbeef")

    def test_no_env_no_auto_generate_returns_none_or_dpapi(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without env + auto_generate=False, return None unless DPAPI has a key."""
        monkeypatch.delenv(HMAC_KEY_NAME, raising=False)
        # Mock DPAPI to return None
        import harness.audit_chain as ac
        original_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict) else __builtins__.__import__

        def fake_import(name: str, *args: object, **kwargs: object):
            if name == "harness.secrets.dpapi":
                raise NotImplementedError("non-Windows test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(
            "builtins.__import__", fake_import, raising=False,
        )
        # Re-importing get_hmac_key via the patched path
        key = get_hmac_key(auto_generate=False)
        assert key is None


# ---------------------------------------------------------------------------
# get_last_chain_hash
# ---------------------------------------------------------------------------


class TestGetLastChainHash:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert get_last_chain_hash(tmp_path / "nope.jsonl") == GENESIS_HASH

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert get_last_chain_hash(p) == GENESIS_HASH

    def test_legacy_only(self, tmp_path: Path) -> None:
        p = tmp_path / "legacy.jsonl"
        p.write_text(json.dumps({"engine": "kimi"}) + "\n",
                     encoding="utf-8")
        assert get_last_chain_hash(p) == GENESIS_HASH

    def test_returns_most_recent_hmac(self, tmp_path: Path) -> None:
        p = tmp_path / "chained.jsonl"
        e1 = {"engine": "kimi", "prev_hash": GENESIS_HASH, "hmac": "a" * 64}
        e2 = {"engine": "deepseek", "prev_hash": "a" * 64, "hmac": "b" * 64}
        p.write_text(
            json.dumps(e1) + "\n" + json.dumps(e2) + "\n",
            encoding="utf-8",
        )
        assert get_last_chain_hash(p) == "b" * 64


# ---------------------------------------------------------------------------
# verify_chain — the canonical lock
# ---------------------------------------------------------------------------


@pytest.fixture()
def hmac_key(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Use a fixed test key via env var (cross-platform)."""
    key_hex = "00112233445566778899aabbccddeeff" * 2  # 32 bytes
    monkeypatch.setenv(HMAC_KEY_NAME, key_hex)
    return bytes.fromhex(key_hex)


def _write_chained_ledger(path: Path, key: bytes, events: list[dict]) -> list[dict]:
    """Helper: write a properly chained sequence of events; return the chained dicts."""
    chained_list = []
    prev = GENESIS_HASH
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            ch = chain_event(e, prev, key)
            chained_list.append(ch)
            f.write(json.dumps(ch) + "\n")
            prev = ch["hmac"]
    return chained_list


class TestVerifyChain:
    def test_missing_file(self, tmp_path: Path, hmac_key: bytes) -> None:
        result = verify_chain(tmp_path / "nope.jsonl")
        assert result.ok is True
        assert result.total == 0
        assert result.key_available is True

    def test_empty_file(self, tmp_path: Path, hmac_key: bytes) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        result = verify_chain(p)
        assert result.ok is True
        assert result.total == 0

    def test_legacy_only_ledger(self, tmp_path: Path, hmac_key: bytes) -> None:
        p = tmp_path / "legacy.jsonl"
        p.write_text(
            json.dumps({"engine": "kimi", "tokens_in": 100}) + "\n"
            + json.dumps({"engine": "deepseek", "tokens_in": 200}) + "\n",
            encoding="utf-8",
        )
        result = verify_chain(p)
        assert result.ok is True
        assert result.total == 2
        assert result.legacy == 2
        assert result.chained == 0

    def test_clean_chained_ledger(self, tmp_path: Path, hmac_key: bytes) -> None:
        p = tmp_path / "clean.jsonl"
        _write_chained_ledger(p, hmac_key, [
            {"engine": "kimi", "tokens_in": 100},
            {"engine": "deepseek", "tokens_in": 200},
            {"engine": "mimo", "tokens_in": 50},
        ])
        result = verify_chain(p)
        assert result.ok is True
        assert result.total == 3
        assert result.chained == 3
        assert result.legacy == 0
        assert result.chain_restarts == (1,)  # only the file-start restart

    def test_detects_tampered_hmac(self, tmp_path: Path, hmac_key: bytes) -> None:
        p = tmp_path / "tampered.jsonl"
        _write_chained_ledger(p, hmac_key, [
            {"engine": "kimi"},
            {"engine": "deepseek"},
            {"engine": "mimo"},
        ])
        # Flip a single hex digit in the middle entry's hmac
        lines = p.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[1])
        # Mutate the hmac so it no longer reproduces
        original = obj["hmac"]
        obj["hmac"] = ("0" if original[0] != "0" else "1") + original[1:]
        lines[1] = json.dumps(obj)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(p)
        assert result.ok is False
        assert result.first_tamper_line == 2
        assert "hmac mismatch" in (result.reason or "")

    def test_detects_tampered_payload_field(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """Flip the engine name — hmac must not reproduce."""
        p = tmp_path / "payload-tamper.jsonl"
        _write_chained_ledger(p, hmac_key, [
            {"engine": "kimi", "tokens_in": 100},
            {"engine": "deepseek", "tokens_in": 200},
        ])
        lines = p.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[0])
        # Tamper a non-hmac field — hmac no longer reproduces
        obj["engine"] = "MALICIOUS"
        lines[0] = json.dumps(obj)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(p)
        assert result.ok is False
        assert result.first_tamper_line == 1

    def test_detects_tampered_prev_hash(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """A wrong prev_hash on entry 2 (with correct hmac) is still tamper.

        Note: if hmac is recomputed for the new prev_hash, the chain
        breaks at LINE 2 because its prev_hash no longer matches LINE 1's
        hmac.  If hmac is NOT recomputed, it breaks because hmac doesn't
        reproduce.  Either way, verify fails.
        """
        p = tmp_path / "prev-tamper.jsonl"
        _write_chained_ledger(p, hmac_key, [
            {"engine": "kimi"},
            {"engine": "deepseek"},
            {"engine": "mimo"},
        ])
        lines = p.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[1])
        # Point prev_hash at a fake hash; hmac no longer matches
        obj["prev_hash"] = "f" * 64
        lines[1] = json.dumps(obj)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_chain(p)
        assert result.ok is False
        assert result.first_tamper_line == 2

    def test_legacy_then_chained_treated_as_restart(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """An old legacy entry followed by a chained run is OK.

        Represents the post-upgrade scenario where the file existed
        before W14-AUDIT-CHAIN-HMAC shipped.
        """
        p = tmp_path / "mixed.jsonl"
        legacy = {"engine": "kimi", "tokens_in": 100}
        prev = GENESIS_HASH
        chained_a = chain_event({"engine": "deepseek"}, prev, hmac_key)
        chained_b = chain_event({"engine": "mimo"}, chained_a["hmac"], hmac_key)
        p.write_text(
            json.dumps(legacy) + "\n"
            + json.dumps(chained_a) + "\n"
            + json.dumps(chained_b) + "\n",
            encoding="utf-8",
        )
        result = verify_chain(p)
        assert result.ok is True
        assert result.legacy == 1
        assert result.chained == 2
        # The chained run after the legacy is a chain restart
        assert 2 in result.chain_restarts

    def test_handles_malformed_lines(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """Garbage JSON lines should be skipped, not fail verification."""
        p = tmp_path / "with-garbage.jsonl"
        chained_a = chain_event({"engine": "kimi"}, GENESIS_HASH, hmac_key)
        p.write_text(
            "this is not json\n"
            + json.dumps(chained_a) + "\n"
            + "{also not balanced\n",
            encoding="utf-8",
        )
        result = verify_chain(p)
        assert result.ok is True
        assert result.chained == 1

    def test_no_key_chained_entries_unverified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without a key, verifier still walks but skips hmac compute.

        Chain-order check still runs (catches prev_hash inconsistencies)
        but hmac forgery cannot be detected — so result is advisory only.
        """
        monkeypatch.delenv(HMAC_KEY_NAME, raising=False)
        key = b"x" * 32
        p = tmp_path / "no-key.jsonl"
        _write_chained_ledger(p, key, [{"engine": "kimi"}, {"engine": "deepseek"}])
        # Mock DPAPI to return no key by patching at import site
        from harness import audit_chain as ac
        original_get_key = ac.get_hmac_key
        monkeypatch.setattr(ac, "get_hmac_key",
                            lambda **kw: None)
        try:
            result = verify_chain(p)
        finally:
            monkeypatch.setattr(ac, "get_hmac_key", original_get_key)
        assert result.key_available is False
        # Chain-order pass through; ok=True because no order violation
        assert result.ok is True

    def test_post_prune_chain_restart_accepted(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """Simulate prune: first kept entry has prev_hash pointing to a
        now-deleted entry.  Verifier should accept this as a chain restart
        (consistent with the file-start case).
        """
        p = tmp_path / "post-prune.jsonl"
        # Build full chain in memory
        prev = GENESIS_HASH
        events = []
        for engine in ["kimi", "deepseek", "mimo", "qwen"]:
            ch = chain_event({"engine": engine}, prev, hmac_key)
            events.append(ch)
            prev = ch["hmac"]
        # "Prune" by writing only the last 2 — first kept entry's
        # prev_hash now points to a deleted hash
        p.write_text(
            json.dumps(events[2]) + "\n" + json.dumps(events[3]) + "\n",
            encoding="utf-8",
        )
        result = verify_chain(p)
        assert result.ok is True
        assert result.chained == 2
        assert result.chain_restarts == (1,)


# ---------------------------------------------------------------------------
# End-to-end integration with append_dispatch_event
# ---------------------------------------------------------------------------


class TestIntegrationWithAppendEvent:
    def test_append_writes_chain_fields(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        from harness.audit_jsonl import append_dispatch_event
        p = tmp_path / "live.jsonl"
        ok = append_dispatch_event(
            engine="kimi",
            model="kimi-for-coding",
            dispatch_id="abc123",
            success=True,
            error=None,
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.05,
            elapsed_ms=4218,
            ledger_path=p,
        )
        assert ok is True
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["prev_hash"] == GENESIS_HASH
        assert "hmac" in obj
        assert len(obj["hmac"]) == 64

    def test_two_appends_chain_correctly(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        from harness.audit_jsonl import append_dispatch_event
        p = tmp_path / "two.jsonl"
        for engine in ["kimi", "deepseek"]:
            append_dispatch_event(
                engine=engine, model="m", dispatch_id=None,
                success=True, error=None, tokens_in=1, tokens_out=1,
                cost_usd=0.0, elapsed_ms=1, ledger_path=p,
            )
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        e2 = json.loads(lines[1])
        assert e1["prev_hash"] == GENESIS_HASH
        assert e2["prev_hash"] == e1["hmac"]

        result = verify_chain(p)
        assert result.ok is True
        assert result.chained == 2

    def test_chain_breaks_after_manual_tamper(
        self, tmp_path: Path, hmac_key: bytes,
    ) -> None:
        """End-to-end: write 3 events, tamper the middle, verifier flags it."""
        from harness.audit_jsonl import append_dispatch_event
        p = tmp_path / "tamper.jsonl"
        for engine in ["kimi", "deepseek", "mimo"]:
            append_dispatch_event(
                engine=engine, model="m", dispatch_id=None,
                success=True, error=None, tokens_in=1, tokens_out=1,
                cost_usd=0.0, elapsed_ms=1, ledger_path=p,
            )
        # Verify clean first
        assert verify_chain(p).ok is True
        # Tamper middle entry's success field
        lines = p.read_text(encoding="utf-8").splitlines()
        obj = json.loads(lines[1])
        obj["success"] = False
        lines[1] = json.dumps(obj)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_chain(p)
        assert result.ok is False
        assert result.first_tamper_line == 2

    def test_append_without_key_writes_legacy_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If key resolution fails, event still writes — without chain fields."""
        monkeypatch.delenv(HMAC_KEY_NAME, raising=False)
        # Patch get_hmac_key to return None
        from harness import audit_chain as ac
        monkeypatch.setattr(ac, "get_hmac_key", lambda **kw: None)

        from harness.audit_jsonl import append_dispatch_event
        p = tmp_path / "legacy.jsonl"
        ok = append_dispatch_event(
            engine="kimi", model="m", dispatch_id=None,
            success=True, error=None, tokens_in=1, tokens_out=1,
            cost_usd=0.0, elapsed_ms=1, ledger_path=p,
        )
        assert ok is True
        obj = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
        assert "prev_hash" not in obj
        assert "hmac" not in obj
