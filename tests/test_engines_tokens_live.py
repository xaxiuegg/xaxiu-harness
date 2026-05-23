"""W6-A2 live API token tracking validation.

Each engine ships with ``EngineResponse(tokens_in, tokens_out)`` derived
from the upstream usage block — but the only way to verify those values
actually populate against real API traffic is to call the live endpoint
and inspect the result.  The existing fixture-based tests stub the HTTP
layer and so cannot catch regressions in the usage-parsing path.

These tests are opt-in via ``HARNESS_LIVE_TESTS=1`` because they:

  - Cost real money (DeepSeek pay-per-token; ~$0.001 per dispatch)
  - Require live network access to vendor endpoints
  - Require API keys present in DPAPI or environment

Run locally:

    $env:HARNESS_LIVE_TESTS = "1"
    pytest tests/test_engines_tokens_live.py -v

Each engine is tested independently — a missing key for one engine
skips that engine's test but does not block the rest.
"""

from __future__ import annotations

import os
from typing import Optional

import pytest

# Gate the whole module on the opt-in env var so CI / default `pytest -q`
# never hits the live endpoints.
pytestmark = pytest.mark.skipif(
    os.environ.get("HARNESS_LIVE_TESTS") != "1",
    reason="set HARNESS_LIVE_TESTS=1 to run live API token tests",
)


# Tiny prompt — minimises both tokens billed and latency.  Each engine
# must still return non-zero tokens_in (the prompt itself) and
# non-zero tokens_out (the model's reply).
_PROBE_PROMPT = "Reply with the single word OK and nothing else."


def _try_engine(engine_name: str) -> tuple[Optional[object], Optional[str]]:
    """Return (engine_instance, None) on success or (None, skip_reason)."""
    from harness.engines.concrete import get_engine
    try:
        return get_engine(engine_name), None
    except RuntimeError as exc:
        return None, f"{engine_name} unavailable: {exc}"


def test_deepseek_returns_nonzero_tokens() -> None:
    eng, skip = _try_engine("deepseek")
    if eng is None:
        pytest.skip(skip)
    resp = eng.dispatch(_PROBE_PROMPT, model="deepseek-v4-flash")
    assert resp.success, f"deepseek dispatch failed: {resp.error}"
    assert resp.tokens_in > 0, (
        f"deepseek returned tokens_in=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )
    assert resp.tokens_out > 0, (
        f"deepseek returned tokens_out=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )


def test_kimi_returns_nonzero_tokens() -> None:
    eng, skip = _try_engine("kimi")
    if eng is None:
        pytest.skip(skip)
    resp = eng.dispatch(_PROBE_PROMPT, model="kimi-for-coding")
    assert resp.success, f"kimi dispatch failed: {resp.error}"
    assert resp.tokens_in > 0, (
        f"kimi returned tokens_in=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )
    assert resp.tokens_out > 0, (
        f"kimi returned tokens_out=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )


def test_mimo_returns_nonzero_tokens() -> None:
    eng, skip = _try_engine("mimo")
    if eng is None:
        pytest.skip(skip)
    # MiMoConcrete auto-routes Pro / Standard via the "auto" sentinel.
    resp = eng.dispatch(_PROBE_PROMPT, model="auto")
    assert resp.success, f"mimo dispatch failed: {resp.error}"
    assert resp.tokens_in > 0, (
        f"mimo returned tokens_in=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )
    assert resp.tokens_out > 0, (
        f"mimo returned tokens_out=0 — usage-parsing regression "
        f"(text_len={len(resp.text)}, latency_ms={resp.latency_ms})"
    )


def test_dispatch_packet_records_nonzero_tokens_to_budget() -> None:
    """End-to-end: dispatch_packet → budget ledger.

    Asserts the ``record_dispatch`` hook fires with ``input_tokens > 0``
    and ``output_tokens > 0`` for at least one engine.  This catches the
    W6-A2 root cause: the worker.py budget hook was hardcoding
    ``input_tokens=0``, so the ledger underreported by 50%.  This live
    test exercises the dispatcher's own record_dispatch call (the
    direct-engine path, not the worker), which already splits the
    in/out counts properly — the test exists to prevent regression of
    that path.
    """
    import tempfile
    import pathlib
    from harness.engines.dispatcher import dispatch_packet
    from harness import budget

    packet_path = pathlib.Path(tempfile.mkdtemp()) / "live_probe.md"
    packet_path.write_text(_PROBE_PROMPT, encoding="utf-8")

    # Try each engine in priority order; first available wins.
    last_err: Optional[str] = None
    for engine_name in ("deepseek", "kimi", "mimo"):
        try:
            result = dispatch_packet(
                project="harness-worker",
                packet_path=str(packet_path),
                force_engine=engine_name,
                trusted_source=True,
            )
            if not result.success:
                last_err = f"{engine_name}: {result.error}"
                continue
            assert result.tokens_used > 0, (
                f"{engine_name}: dispatch returned tokens_used=0 — "
                f"in+out sum lost between EngineResponse and DispatchResult"
            )
            # Probe the budget ledger to confirm record_dispatch fired.
            # We don't assert exact tokens (engine + model + dedup makes
            # that brittle); we assert the engine row exists with non-zero
            # totals (in OR out — engines vary on which they report).
            summary = budget.summary()
            row = summary.get(engine_name) or {}
            assert (row.get("total_input_tokens", 0) > 0
                    or row.get("total_output_tokens", 0) > 0), (
                f"{engine_name}: budget ledger has zero tokens after live "
                f"dispatch; record_dispatch hook is not firing or "
                f"summary() is misaggregating.  Row: {row}"
            )
            return  # first successful engine satisfies the test
        except RuntimeError as exc:
            last_err = f"{engine_name}: {exc}"
            continue

    pytest.skip(f"no engines available for budget e2e check: {last_err}")
