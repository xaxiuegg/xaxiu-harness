"""xaxiu-harness error taxonomy.

Two-axis tag: L<level>.<domain>.<code>.  See spec/errors.md for the full
taxonomy and operator-facing semantics.

Levels: 1=INFO, 2=WARN, 3=ERROR, 4=CRITICAL, 5=FATAL.  Only L5 escalates to
the operator under the full-dev-authority directive; L1-L4 are handled
autonomously by the dev loop.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

__all__ = [
    "HarnessError",
    "Domain",
    "Level",
    "DispatchExhausted",
    "EngineTimeout",
    "EngineRefusal",
    "PacketTrap",
    "SchemaViolation",
    "DpapiUnreadable",
    "AllEnginesUnreachable",
    "GitPushFailed",
    "ConfigCorruption",
    "WavePersistentlyFailing",
    "StateLockTimeout",
    "WorktreeMissing",
    "ALLOWED_DOMAINS",
    "ALLOWED_LEVELS",
    "format_escalation_banner",
    "handle_harness_error",
]

Domain = Literal[
    "dispatch", "engines", "state", "secrets", "schema",
    "network", "config", "observer",
]
Level = Literal[1, 2, 3, 4, 5]

ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "dispatch", "engines", "state", "secrets", "schema",
    "network", "config", "observer",
})
ALLOWED_LEVELS: frozenset[int] = frozenset({1, 2, 3, 4, 5})


class HarnessError(Exception):
    """Base for all xaxiu-harness errors.

    Subclasses set ``level``, ``domain``, ``code`` as class attributes.
    Instances supply ``message`` and optional ``context``.
    """

    level: ClassVar[int] = 3
    domain: ClassVar[str] = "config"
    code: ClassVar[str] = "E_UNSPECIFIED"

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        if self.level not in ALLOWED_LEVELS:
            raise ValueError(f"invalid level for {type(self).__name__}: {self.level}")
        if self.domain not in ALLOWED_DOMAINS:
            raise ValueError(f"invalid domain for {type(self).__name__}: {self.domain}")
        if not self.code.startswith("E_"):
            raise ValueError(f"code for {type(self).__name__} must start with 'E_': {self.code}")
        super().__init__(message)
        self.message: str = message
        self.context: dict[str, Any] = dict(context) if context else {}

    def tag(self) -> str:
        """Return ``L<level>.<domain>.<code>``."""
        return f"L{self.level}.{self.domain}.{self.code}"

    def exit_code(self) -> int:
        """Map level to CLI exit code (0/0/1/3/4 for L1/L2/L3/L4/L5)."""
        return {1: 0, 2: 0, 3: 1, 4: 3, 5: 4}[self.level]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable payload (for jsonl logging)."""
        return {
            "tag": self.tag(),
            "level": self.level,
            "domain": self.domain,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.tag()}: {self.message!r})"


# ---------------------------------------------------------------------------
# L3 — recoverable operational failures
# ---------------------------------------------------------------------------

class DispatchExhausted(HarnessError):
    """All engines failed for a single packet; auto-fallback chain exhausted."""
    level = 3
    domain = "dispatch"
    code = "E_DISPATCH_EXHAUSTED"


class EngineTimeout(HarnessError):
    """Engine HTTP client exceeded the configured timeout."""
    level = 3
    domain = "engines"
    code = "E_ENGINE_TIMEOUT"


class EngineRefusal(HarnessError):
    """Engine returned a refusal pattern (caught by engine guards)."""
    level = 3
    domain = "engines"
    code = "E_ENGINE_REFUSAL"


class StateLockTimeout(HarnessError):
    """Could not acquire an advisory file lock within the configured timeout."""
    level = 3
    domain = "state"
    code = "E_STATE_LOCK_TIMEOUT"


# ---------------------------------------------------------------------------
# L4 — integrity threats; quarantine, no global halt
# ---------------------------------------------------------------------------

class PacketTrap(HarnessError):
    """Engine emitted a tool-call attempt (DSML) instead of patch text."""
    level = 4
    domain = "engines"
    code = "E_PACKET_TRAP"


class SchemaViolation(HarnessError):
    """Closed-schema violation (unknown field, type mismatch) on read or write."""
    level = 4
    domain = "schema"
    code = "E_SCHEMA_VIOLATION"


class WorktreeMissing(HarnessError):
    """Worker dispatch attempted against a worktree path that does not exist.

    Surfaces battle-test 2026-05-21 defect: ``_dispatch_via_swarm`` used to
    silently fall back to ``cwd=None`` when the worktree was missing, which
    let agentic engines mutate the main repo by accident.  Raising L4 stops
    the dispatch dead and lets the coord layer recover (create the worktree
    on retry, or escalate if recovery fails).
    """
    level = 4
    domain = "dispatch"
    code = "E_MISSING_WORKTREE"


# ---------------------------------------------------------------------------
# L5 — operator action needed; affected phase pauses with auto-retry
# ---------------------------------------------------------------------------

class DpapiUnreadable(HarnessError):
    """DPAPI secret store cannot be decrypted on this machine."""
    level = 5
    domain = "secrets"
    code = "E_DPAPI_UNREADABLE"


class AllEnginesUnreachable(HarnessError):
    """Every registered engine is in cooldown or network-unreachable."""
    level = 5
    domain = "network"
    code = "E_ALL_ENGINES_UNREACHABLE"


class GitPushFailed(HarnessError):
    """git push failed for auth or network reasons (not branch protection)."""
    level = 5
    domain = "network"
    code = "E_PUSH_FAILED"


class ConfigCorruption(HarnessError):
    """Adapter YAML or state.json failed to parse / validate."""
    level = 5
    domain = "config"
    code = "E_CONFIG_CORRUPTION"


class WavePersistentlyFailing(HarnessError):
    """Same wave failed across both engines on 3+ retries."""
    level = 5
    domain = "dispatch"
    code = "E_WAVE_PERSISTENTLY_FAILING"


# ---------------------------------------------------------------------------
# W5-Y operator-escalation contract
#
# Memory directive 2026-05-20: "only L5 escalates to operator under
# full-dev-authority directive; L1-L4 are handled autonomously by the
# dev loop."  Concretize that contract as a callable so every code
# path that catches a HarnessError can route it the same way:
#
#   try:
#       ...
#   except HarnessError as exc:
#       handle_harness_error(exc)
#
# The banner format is stable so observer / log scrapers can grep for
# "OPERATOR ESCALATION (L5)" reliably.
# ---------------------------------------------------------------------------

def format_escalation_banner(exc: HarnessError) -> str:
    """Render the human-facing escalation banner for an L5 error.

    Always returns the same shape — observer scrapers can grep for the
    leading "*** OPERATOR ESCALATION (L5) ***" marker.  Lower-level
    errors return a single-line summary (no banner).
    """
    if exc.level >= 5:
        return (
            "\n"
            "*** OPERATOR ESCALATION (L5) ***\n"
            f"  tag:     {exc.tag()}\n"
            f"  domain:  {exc.domain}\n"
            f"  code:    {exc.code}\n"
            f"  message: {exc.message}\n"
            "*** action: operator review required ***\n"
        )
    return f"[{exc.tag()}] {exc.message}"


def handle_harness_error(
    exc: HarnessError,
    *,
    stderr_writer: Any = None,
    sys_exit: Any = None,
) -> int:
    """Print the escalation banner + return the exit code.

    Does NOT call ``sys.exit`` by default — caller decides whether to
    terminate or recover.  Pass ``sys_exit=sys.exit`` to force
    termination.  ``stderr_writer`` defaults to ``sys.stderr.write``.

    Returns the exit code (0 for L1-L2, 1 for L3, 3 for L4, 4 for L5).
    """
    import sys as _sys
    write = stderr_writer or _sys.stderr.write
    write(format_escalation_banner(exc) + "\n")
    code = exc.exit_code()
    if sys_exit is not None:
        sys_exit(code)
    return code
