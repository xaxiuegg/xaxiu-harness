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
    ReviewResult,
    capabilities,
    dispatch,
    retrieve,
    review,
    budget_status,
)

# W13 Wed-Thu bundle 2026-05-25: the multi-engine review pipeline lives
# in ``harness.reviewer`` (NOT ``harness.review``).  The SDK function
# ``harness.review`` would collide with a same-named submodule, so we
# renamed the module to avoid that.  Anyone wanting the lower-level
# bits — review_document(), Lens, LENS_SETS, infer_lens_set,
# auto_max_tokens — should import from ``harness.reviewer``.

__all__ = [
    "__version__",
    "DispatchResult",
    "HarnessSDKError",
    "ResultNotFoundError",
    "ResultCorruptedError",
    "ReturnMode",
    "RetrieveScope",
    "ReviewResult",
    "capabilities",
    "dispatch",
    "retrieve",
    "review",
    "budget_status",
]
