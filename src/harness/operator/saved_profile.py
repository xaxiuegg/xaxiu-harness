"""W10-PROFILE-AWARE-DEFAULTS: persisted operator profile.

The operator's profile (`technical` vs `non_technical`) determines
how verbosely commands report errors, what packet templates are
used, and which "advanced" surfaces are visible.  Today the
`--profile` flag exists on commands that take operator-modes but
isn't persisted — the operator has to repeat it every invocation.

This module persists the choice to ``~/.harness/profile.json`` via
the W9-STATE-ATOMIC-WRITES canonical helper.  CLI commands that
already take ``--profile`` can fall back to the saved value when
the flag isn't passed.

Schema (JSON):
    {
        "schema_version": 1,
        "profile": "technical" | "non_technical",
        "updated_at": "<iso-8601>"
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


SCHEMA_VERSION = 1
ALLOWED_PROFILES: tuple[str, ...] = ("technical", "non_technical")


def default_profile_path() -> Path:
    """Return the canonical path: ``~/.harness/profile.json``."""
    return Path.home() / ".harness" / "profile.json"


@dataclass(frozen=True)
class SavedProfile:
    profile: Literal["technical", "non_technical"]
    updated_at: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "updated_at": self.updated_at,
        }


def save_profile(profile: str, *, path: Path | None = None) -> SavedProfile:
    """Persist *profile* atomically.  Raises ``ValueError`` on unknown profile."""
    if profile not in ALLOWED_PROFILES:
        raise ValueError(
            f"unknown profile {profile!r}; allowed: "
            f"{sorted(ALLOWED_PROFILES)}"
        )
    target = path or default_profile_path()
    record = SavedProfile(
        profile=profile,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    # Use W9-STATE-ATOMIC-WRITES canonical helper.  set_mode_0600=False
    # since ~/.harness/profile.json is not sensitive (no secrets).
    from harness.state.files import atomic_write_json
    atomic_write_json(target, record.to_dict(), set_mode_0600=False)
    return record


def load_profile(*, path: Path | None = None) -> SavedProfile | None:
    """Read the saved profile or return None if missing / invalid.

    Returns None (not raises) on missing/corrupt: callers fall back
    to either the --profile flag or the OperatorMode default.
    """
    target = path or default_profile_path()
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    profile = raw.get("profile")
    if profile not in ALLOWED_PROFILES:
        return None
    return SavedProfile(
        profile=profile,
        updated_at=raw.get("updated_at", ""),
        schema_version=raw.get("schema_version", SCHEMA_VERSION),
    )


def resolve_profile(cli_flag: str | None,
                    *, path: Path | None = None) -> str | None:
    """Return the profile to use.

    Order of precedence:
      1. CLI flag (highest — explicit operator intent)
      2. Saved profile from ~/.harness/profile.json
      3. None (caller falls back to OperatorMode default)
    """
    if cli_flag:
        return cli_flag
    saved = load_profile(path=path)
    if saved is None:
        return None
    return saved.profile
