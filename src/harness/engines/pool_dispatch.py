"""W14-KEYS-POOL-P2 2026-05-26: dispatch through a key pool with
health-aware selection + automatic failover on auth/quota failures.

This is the missing wire between the resolver (which knows how to
PICK a key from the pool) and the engine (which doesn't know about
pools at all).  Without this, multi-key configuration is just data
- nothing automatically rotates or fails over.

API
===

  from harness.engines.pool_dispatch import dispatch_with_pool

  result = dispatch_with_pool(
      "kimi-via-claude",         # provider name
      "explain X in one sentence",
      extra_args={"max_budget_usd": 0.10},
      max_retries=3,
  )
  # result.success is True if any key in the pool succeeded
  # result.attempts is a list of (alias, success, error) tuples
  # showing which keys were tried in what order

Behavior
========

1. Calls ``pick_next_key(env_prefix, honor_health=True)`` to get the
   best key per current policy + health.
2. Builds the appropriate engine with that key.
3. Dispatches the prompt.
4. On success: records "up" to the health ledger, returns response.
5. On failure:
   a. Classifies the failure (auth-failed / quota-exceeded /
      transient / unknown).
   b. Records the outcome to the health ledger.
   c. If failure is auth/quota and retries remain, excludes this
      alias and tries the next pick.
   d. If failure is transient/unknown, does NOT failover (the
      failure may be retryable on the same key).

Integration-test surface
========================

This module is the integration point the audit panel said was
missing.  Tests configure two keys (first deliberately invalid),
dispatch through this function, and assert: (a) response generated,
(b) both keys tried in order, (c) health ledger reflects the
failure of the first key.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from harness.engines.base import EngineResponse

logger = logging.getLogger(__name__)


# Map provider name → env-var prefix.  Single source of truth.
_PROVIDER_TO_PREFIX: dict[str, str] = {
    "kimi-via-claude":      "KIMI_API_KEY",
    "mimo-via-claude":      "MIMO_API_KEY",
    "deepseek-via-claude":  "DEEPSEEK_API_KEY",
}


# Failure-category mapping: which classifications cause failover?
# Convergent with the keys.health module's classification scheme.
_FAILOVER_CATEGORIES: frozenset[str] = frozenset({
    "auth-failed",
    "quota-exceeded",
    "terminated",
})


@dataclass
class PoolAttempt:
    """One attempt within a pool dispatch."""
    alias: str
    env_var: str
    success: bool
    category: str  # "up" / "auth-failed" / "quota-exceeded" / ...
    error: str = ""
    latency_ms: int = 0


@dataclass
class PoolDispatchResult:
    """Result of a pool-aware dispatch."""
    success: bool
    response: Optional[EngineResponse] = None
    attempts: list[PoolAttempt] = field(default_factory=list)
    winning_alias: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def _classify_failure(resp: EngineResponse) -> str:
    """Classify an EngineResponse error into a health-ledger category."""
    if resp.success:
        return "up"
    err = (resp.error or "").lower()
    if any(s in err for s in ("auth", "401", "403", "invalid api key",
                              "unauthorized", "forbidden")):
        return "auth-failed"
    if any(s in err for s in ("quota", "rate limit", "429",
                              "credit", "budget exceeded")):
        return "quota-exceeded"
    if any(s in err for s in ("terminated", "account suspended",
                              "account disabled")):
        return "terminated"
    if any(s in err for s in ("timeout", "connection",
                              "network", "503", "502", "504")):
        return "transient"
    return "unknown-failure"


def _build_engine_with_key(provider_name: str, api_key: str):
    """Construct the appropriate engine subclass for the provider
    using a specific key (NOT resolved from env)."""
    from harness.engines.claude_code_subprocess import (
        DeepSeekViaClaudeCodeEngine,
        KimiViaClaudeCodeEngine,
        MimoViaClaudeCodeEngine,
    )
    if provider_name == "kimi-via-claude":
        return KimiViaClaudeCodeEngine(api_key=api_key)
    if provider_name == "mimo-via-claude":
        return MimoViaClaudeCodeEngine(api_key=api_key)
    if provider_name == "deepseek-via-claude":
        return DeepSeekViaClaudeCodeEngine(api_key=api_key)
    raise ValueError(
        f"dispatch_with_pool does not support engine {provider_name!r}. "
        f"Supported: {list(_PROVIDER_TO_PREFIX)}"
    )


def dispatch_with_pool(
    provider_name: str,
    prompt: str,
    *,
    model: str = "",
    extra_args: Optional[dict] = None,
    max_retries: int = 3,
    strategy: Optional[str] = None,
    engine_builder=None,  # test-injection seam
) -> PoolDispatchResult:
    """Dispatch ``prompt`` through ``provider_name``, picking keys
    from the pool with health-aware selection + auth/quota failover.

    Parameters
    ----------
    provider_name
        One of ``"kimi-via-claude" / "mimo-via-claude" / "deepseek-
        via-claude"``.
    prompt
        Packet content to dispatch.
    model
        Optional model override; if empty, the engine's default is used.
    extra_args
        Forwarded to the engine's ``dispatch()`` call.
    max_retries
        How many keys to try before giving up.  Defaults to 3.  Note:
        this counts TOTAL attempts including the first; max_retries=1
        means "try one key, don't failover".
    strategy
        Override the per-provider failover strategy (rotation /
        priority / failover-only).  Defaults to the persisted policy.
    engine_builder
        Test seam.  When provided, this callable is used instead of
        the real engine constructor.  Signature: ``(provider_name,
        api_key) -> engine_with_dispatch_method``.

    Returns
    -------
    PoolDispatchResult
        ``success`` reflects whether ANY key in the pool succeeded.
        ``attempts`` lists every key tried in order.  ``winning_alias``
        is the alias that succeeded (empty string if all failed).
    """
    from harness.keys import pick_next_key, record_outcome

    if provider_name not in _PROVIDER_TO_PREFIX:
        raise ValueError(
            f"dispatch_with_pool does not support engine "
            f"{provider_name!r}.  Supported: "
            f"{list(_PROVIDER_TO_PREFIX)}"
        )
    env_prefix = _PROVIDER_TO_PREFIX[provider_name]
    excluded: set[str] = set()
    attempts: list[PoolAttempt] = []
    extra = extra_args or {}

    for attempt_n in range(max_retries):
        entry = pick_next_key(
            env_prefix,
            strategy=strategy,
            exclude_aliases=excluded,
            honor_health=True,
        )
        if entry is None:
            logger.info(
                "pool_dispatch[%s]: no eligible key after %d attempt(s); "
                "stopping",
                provider_name, attempt_n,
            )
            break

        # Build engine - real or injected
        try:
            if engine_builder is not None:
                eng = engine_builder(provider_name, entry.value)
            else:
                eng = _build_engine_with_key(
                    provider_name, entry.value,
                )
        except Exception as exc:
            logger.error(
                "pool_dispatch[%s]: engine build failed for %s: %s",
                provider_name, entry.alias, exc,
            )
            attempts.append(PoolAttempt(
                alias=entry.alias, env_var=entry.env_var,
                success=False, category="unknown-failure",
                error=f"engine build: {exc}",
            ))
            excluded.add(entry.alias)
            continue

        # Dispatch
        try:
            resp = eng.dispatch(prompt, model, extra)
        except Exception as exc:
            resp = EngineResponse(
                success=False, text="",
                latency_ms=0,
                error=f"{type(exc).__name__}: {exc}",
            )

        category = _classify_failure(resp)
        attempts.append(PoolAttempt(
            alias=entry.alias, env_var=entry.env_var,
            success=resp.success,
            category=category,
            error=resp.error or "",
            latency_ms=resp.latency_ms or 0,
        ))

        # Record outcome to the health ledger so future picks see it
        try:
            record_outcome(
                env_prefix, entry.alias, entry.env_var,
                category,
                source="dispatch",
                details=resp.error or "" if not resp.success else "",
            )
        except Exception:
            pass  # telemetry never blocks dispatch

        if resp.success:
            return PoolDispatchResult(
                success=True, response=resp,
                attempts=attempts, winning_alias=entry.alias,
            )

        # Decide whether to failover
        if category in _FAILOVER_CATEGORIES:
            excluded.add(entry.alias)
            logger.info(
                "pool_dispatch[%s]: %s failed with %s; failing over",
                provider_name, entry.alias, category,
            )
            continue
        else:
            # transient / unknown — don't failover (caller can retry
            # same key later when the transient issue clears).  Return
            # the last response so the caller sees the error.
            logger.info(
                "pool_dispatch[%s]: %s failed with %s; not retrying "
                "(transient)",
                provider_name, entry.alias, category,
            )
            return PoolDispatchResult(
                success=False, response=resp,
                attempts=attempts, winning_alias="",
            )

    # Exhausted attempts
    last_resp = attempts[-1] if attempts else None
    last_response_obj = None
    if last_resp:
        last_response_obj = EngineResponse(
            success=False, text="",
            latency_ms=last_resp.latency_ms,
            error=last_resp.error,
        )
    return PoolDispatchResult(
        success=False, response=last_response_obj,
        attempts=attempts, winning_alias="",
    )
