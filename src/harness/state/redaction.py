"""W9-REDACTION-INTEGRITY-TEST: canonical secret-redaction patterns.

M09 worst-case path: prompt injection → engine exfiltrates key
material into response → response logged via retro/replay/today/
panic-dump BEFORE redaction runs.  Master audit found no
redaction-integrity tests anywhere.

W9 consolidates the redaction patterns (previously duplicated
across ``state/jsonl_log._redact`` and ``panic._scrub_text``) into
one module so:

  - Adding a new pattern (e.g. a new vendor's key prefix) updates
    every output surface at once.
  - The test suite can pin a single ground-truth list of patterns
    to scan against, ensuring no surface diverges silently.

Patterns covered:

  - ``sk-...`` — OpenAI / Anthropic-style API key prefix
  - ``Bearer <token>`` — OAuth / OIDC bearer
  - ``api_key`` / ``api-key`` / ``apikey`` named values
  - ``ms-...`` — MiMo prefix
  - ``deepseek-<token>``
  - ``tp-...`` — MiMo Token Plan subscription key prefix
  - ``mt-...`` / ``moon-...`` — Moonshot / Kimi vendor variants
  - ``(KIMI|DEEPSEEK|ANTHROPIC|GEMINI|MOONSHOT|OPENAI|MIMO)_API_KEY=<value>``
  - DPAPI base64 blob: magic-bytes ``AQAAAN...`` (DPAPI blobs almost
    always start with this byte sequence when base64-encoded)
"""

from __future__ import annotations

import re
from typing import Final


# All patterns must capture the secret-bearing portion.  Two-group
# patterns preserve the leading label (e.g. "KIMI_API_KEY=") and
# replace only the value side.
_PATTERNS_SUB: Final[tuple[re.Pattern[str], ...]] = (
    # OpenAI / Anthropic-style keys
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    # OAuth bearer (allow underscores in token to match legacy patterns)
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
    re.compile(r"Bearer\s+\S+"),  # broad fallback for short tokens
    # MiMo plain + Token Plan
    re.compile(r"\bms-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\btp-[A-Za-z0-9_\-]{20,}"),
    # Moonshot / Kimi
    re.compile(r"\bmt-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bmoon-[A-Za-z0-9_\-]{20,}"),
    # DeepSeek vendor prefix
    re.compile(r"\bdeepseek-[A-Za-z0-9]{20,}"),
    # api_key style assignment
    re.compile(
        r"(?i)api[_-]?key\s*[\"':=]+\s*[\"']?[A-Za-z0-9_-]{16,}"
    ),
    # DPAPI base64 magic prefix
    re.compile(r"AQAAAN[A-Za-z0-9+/=]{40,}"),
)


# Env-var assignment pattern is special: replace only the value
# (group 2), preserving the label (group 1) so the operator can
# still see WHICH env var was logged.
_ENV_ASSIGN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"((?:KIMI|DEEPSEEK|ANTHROPIC|GEMINI|MOONSHOT|OPENAI|MIMO)_API_KEY"
    r"\s*[:=]\s*['\"]?)([^\s'\"\n]+)"
)


REDACTION_TOKEN: Final[str] = "[REDACTED]"


def redact(text: str | None) -> str | None:
    """Redact every known secret pattern from *text*.

    Returns ``None`` unchanged; non-string callers are coerced via
    ``str()`` so a defensive surface can pass anything.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    # Env-assignment: keep the label, replace value
    text = _ENV_ASSIGN_PATTERN.sub(lambda m: m.group(1) + REDACTION_TOKEN, text)
    for pat in _PATTERNS_SUB:
        text = pat.sub(REDACTION_TOKEN, text)
    return text


def has_unredacted_secret(text: str) -> bool:
    """Return True iff *text* contains any pattern this module would redact.

    Already-redacted text (containing :data:`REDACTION_TOKEN` where a
    secret would be) returns False — the function should be idempotent
    when checking output that already passed through :func:`redact`.

    Useful for integration tests asserting that an output surface's
    rendering pipeline applied redaction.
    """
    env_m = _ENV_ASSIGN_PATTERN.search(text)
    if env_m and env_m.group(2) != REDACTION_TOKEN:
        return True
    for pat in _PATTERNS_SUB:
        m = pat.search(text)
        if m and m.group(0) != REDACTION_TOKEN:
            return True
    return False
