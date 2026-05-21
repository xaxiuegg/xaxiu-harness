"""Routing strategies for the 4-key API proxy pool."""

from __future__ import annotations

import random
from datetime import datetime

from harness.proxy import circuit
from harness.proxy.state import ProxyState


def pick_key(
    state: ProxyState,
    *,
    now: datetime,
    strategy: str = "least_loaded",
) -> str | None:
    """Pick a routable key. Returns ``None`` if the pool is saturated or unhealthy."""
    pool = [
        k for k in state.keys.values()
        if circuit.is_routable(k, now=now) and k.in_flight < k.max_concurrent
    ]
    if not pool:
        return None
    if strategy == "least_loaded":
        pool.sort(key=lambda k: (k.in_flight, k.avg_latency_ms))
    elif strategy == "round_robin":
        pool.sort(key=lambda k: k.key_alias)
        idx = state.total_requests % len(pool)
        return pool[idx].key_alias
    elif strategy == "random":
        random.shuffle(pool)
    return pool[0].key_alias
