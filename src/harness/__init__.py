"""xaxiu-harness — cross-project multi-engine LLM dispatch + monitoring.

Agent-facing Python SDK (W11-PYTHON-SDK-API-STUBS):

    from harness import dispatch, retrieve, budget_status, DispatchResult

The SDK is the agent-friendly programmatic interface.  The CLI
(`harness <verb>`) remains the human-operator path; both surfaces
share the same underlying dispatch/retrieve/budget primitives.

For full API contract see :mod:`harness._sdk`.
"""

__version__ = "0.1.0"

# W11-PYTHON-SDK-API-STUBS 2026-05-25: re-export the stable agent API.
# The function bodies live in harness._sdk and currently raise
# NotImplementedError; real implementations land in W11-PYTHON-SDK-API-IMPL
# (Wave 11-D) after the W11-B context-frugal-return + cache + retrieve
# rows stabilize.
from harness._sdk import (
    DispatchResult,
    HarnessSDKError,
    ResultNotFoundError,
    ResultCorruptedError,
    ReturnMode,
    RetrieveScope,
    dispatch,
    retrieve,
    budget_status,
)

__all__ = [
    "__version__",
    "DispatchResult",
    "HarnessSDKError",
    "ResultNotFoundError",
    "ResultCorruptedError",
    "ReturnMode",
    "RetrieveScope",
    "dispatch",
    "retrieve",
    "budget_status",
]
