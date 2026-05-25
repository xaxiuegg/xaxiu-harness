"""Type stubs for the harness public SDK.

Provides type information for IDE auto-complete + agent code-gen
without forcing every consumer to read the source.  Matches the
runtime contract in harness/_sdk.py.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

__version__: str

ReturnMode = Literal["summary", "full", "ref"]
RetrieveScope = Literal["summary", "full", "chunks"]


@dataclass
class DispatchResult:
    success: bool
    engine_used: str
    dispatch_id: str
    summary: str = ...
    truncated: bool = ...
    error_excerpt: str | None = ...
    content_ref: str | None = ...
    text: str | None = ...
    tokens_in: int = ...
    tokens_out: int = ...
    cost_usd: float = ...
    fallback_chain: list[str] = ...

    def full(self) -> str: ...


@dataclass
class ReviewResult:
    synthesis_path: str
    out_dir: str
    document_text_length: int
    elapsed_s: float
    total_cost_usd: float
    successful_lenses: int
    failed_lenses: int
    lens_set_used: str
    max_tokens_used: int
    lens_results: list[dict] = ...


class HarnessSDKError(Exception): ...
class ResultNotFoundError(HarnessSDKError): ...
class ResultCorruptedError(HarnessSDKError): ...


def dispatch(
    prompt: str,
    engine: str | list[str] | None = ...,
    *,
    return_mode: ReturnMode = ...,
    timeout_sec: float = ...,
    with_full_text: bool = ...,
    no_cache: bool = ...,
) -> DispatchResult: ...


def retrieve(
    dispatch_id: str,
    scope: RetrieveScope = ...,
    *,
    chunk_size_tokens: int = ...,
    project_root: str | None = ...,
) -> str | list[str]: ...


def review(
    document_path: str,
    *,
    lens_set: str | None = ...,
    max_tokens: int | None = ...,
    quick: bool = ...,
    out_dir: str | None = ...,
    max_concurrent: int = ...,
    progress_cb: Callable[[str], None] | None = ...,
) -> ReviewResult: ...


def capabilities() -> dict[str, Any]: ...


def budget_status(
    *,
    since_hours: float | None = ...,
    ledger_path: Any | None = ...,
) -> dict: ...
