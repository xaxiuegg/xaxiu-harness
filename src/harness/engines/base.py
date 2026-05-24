"""Engine ABC and concrete stubs for the xaxiu-harness backend pool.

Engines are pluggable backends. The harness selects one per dispatch per
routing rules + priority + fallback chain.  This module defines the contract
(EngineResponse + Engine ABC) and provides Wave-1 stub implementations for the
three supported backends.

Wave 2 will wire real HTTP calls, engine-specific guards, and health-check
updates into these classes.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

SUPPORTED_BACKENDS = ["deepseek", "kimi", "anthropic"]


@dataclass(frozen=True)
class EngineResponse:
    """Immutable result of a single dispatch attempt.

    Attributes:
        success: Whether the engine produced a usable response.
        text: Generated output text (may be empty on failure).
        latency_ms: Round-trip time in milliseconds.
        error: Human-readable failure reason, or None on success.
        reasoning_only: W7-KIMI-REASONING-EMPTY 2026-05-23.  True when
            the engine emitted reasoning_content but exhausted its
            max_tokens budget BEFORE producing any user-facing content.
            success is True (the API call worked) but text is empty
            and the caller should retry with a larger budget rather
            than relay the empty response downstream.  Currently set
            by KimiConcrete; other engines may opt in similarly.
    """

    success: bool
    text: str
    latency_ms: int
    error: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    reasoning_only: bool = False


class Engine(ABC):
    """Abstract base class for all harness backends."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Store the api key in ``self._api_key`` for use by dispatch().

        Battle-test 2026-05-21: all the v1 Concrete subclasses (KimiConcrete,
        DeepSeekConcrete, AnthropicConcrete, GeminiConcrete) reference
        ``self._api_key`` but never defined an ``__init__``, and the factory
        ``get_engine()`` calls ``cls(api_key=...)`` which would fail with
        ``TypeError: KimiConcrete() takes no arguments``.  Centralising the
        constructor here means every subclass gets it for free.
        """
        self._api_key: Optional[str] = api_key

    @property
    def name(self) -> str:
        """Return the canonical backend name (e.g. 'deepseek').

        Default implementation derives from class name: ``KimiConcrete`` →
        ``"kimi"``, ``DeepSeekStub`` → ``"deepseek"``.  Subclasses may
        override to provide a non-derived name (e.g. ``MockEngine``).
        """
        cls_name = type(self).__name__
        # Strip common suffixes: Concrete, Engine, Stub
        for suffix in ("Concrete", "Engine", "Stub"):
            if cls_name.endswith(suffix):
                cls_name = cls_name[: -len(suffix)]
                break
        # Camel-to-lower: DeepSeek → deepseek
        return cls_name.lower()

    @abstractmethod
    def dispatch(
        self, packet_content: str, model: str, extra_args: dict
    ) -> EngineResponse:
        """Send *packet_content* to the engine and return its response.

        Args:
            packet_content: The full text of the dispatch packet.
            model: Model identifier to use (engine-specific).
            extra_args: Additional flags/options for the call.

        Returns:
            An :class:`EngineResponse` describing the outcome.
        """
        ...


class DeepSeekEngine(Engine):
    """Stub for the DeepSeek backend.

    Wave-2 additions:
    - Auto ``--no-thinking`` for patch packets (paths matching ``*patch*`` or
      ``*FIND/REPLACE*``).
    - Packet-trap suppression: reject boilerplate output that looks like
      ``<gibberish>`` (regex ``^{.*}$``), log as ``packet_trap``, and trigger
      fallback.
    - Anchor-fuzzy post-validator on generated FIND/REPLACE blocks.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        if api_key is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
        self._api_key: Optional[str] = api_key

    @property
    def name(self) -> str:
        return "deepseek"

    def dispatch(
        self, packet_content: str, model: str, extra_args: dict
    ) -> EngineResponse:
        return EngineResponse(
            success=False,
            text="",
            latency_ms=0,
            error="dispatch not implemented in Wave 1",
        )

    def __repr__(self) -> str:
        return f"DeepSeekEngine(api_key={'SET' if self._api_key else 'MISSING'})"


class KimiEngine(Engine):
    """Stub for the Kimi backend.

    Wave-2 additions:
    - Multi-domain bundle splitter: if a packet contains multiple ``domain:``
      headers, split into sub-packets and dispatch each separately.
    - Anchor-fuzzy post-validator on generated FIND/REPLACE blocks.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        if api_key is None:
            api_key = os.environ.get("KIMI_API_KEY")
        self._api_key: Optional[str] = api_key

    @property
    def name(self) -> str:
        return "kimi"

    def dispatch(
        self, packet_content: str, model: str, extra_args: dict
    ) -> EngineResponse:
        return EngineResponse(
            success=False,
            text="",
            latency_ms=0,
            error="dispatch not implemented in Wave 1",
        )

    def __repr__(self) -> str:
        return f"KimiEngine(api_key={'SET' if self._api_key else 'MISSING'})"


class AnthropicEngine(Engine):
    """Stub for the Anthropic backend.

    Wave-2 additions:
    - Anchor-fuzzy post-validator on generated FIND/REPLACE blocks.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        if api_key is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._api_key: Optional[str] = api_key

    @property
    def name(self) -> str:
        return "anthropic"

    def dispatch(
        self, packet_content: str, model: str, extra_args: dict
    ) -> EngineResponse:
        return EngineResponse(
            success=False,
            text="",
            latency_ms=0,
            error="dispatch not implemented in Wave 1",
        )

    def __repr__(self) -> str:
        return f"AnthropicEngine(api_key={'SET' if self._api_key else 'MISSING'})"
