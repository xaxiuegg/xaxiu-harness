"""W11-DPAPI-CROSS-PLATFORM: central key resolver with cross-platform precedence.

Order of precedence (highest priority first):

  1. ``os.environ[name]`` — explicit operator-set env var (e.g. CI secrets,
     `export KIMI_API_KEY=...` in shell)
  2. ``.env`` file in the project's `.harness/` parent dir (cross-platform;
     primary path for non-Windows agents)
  3. DPAPI store (Windows only; gracefully skipped on non-Windows)

This module replaces the pre-W11 direct `dpapi.has_secret/decrypt_secret`
calls in `harness.engines.concrete.get_engine()`.  DPAPI raises
NotImplementedError on non-Windows; we catch + fall through so
Linux/Mac agents work without setting `prefer_dpapi=False` defensively.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from harness.secrets import env_file


def default_env_path(start: Path | None = None) -> Path:
    """Locate the project's .env file.

    Walks up from *start* (or cwd) looking for the first .env adjacent
    to a .harness/ directory.  Falls back to cwd/.env.
    """
    cur = (start or Path.cwd()).resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / ".harness").is_dir() and (parent / ".env").exists():
            return parent / ".env"
    return (start or Path.cwd()) / ".env"


def resolve_key(name: str, *,
                env_file_path: Path | None = None,
                prefer_dpapi: bool = False) -> str | None:
    """Return the secret value for *name* via the cross-platform fallback chain.

    Returns None if the key isn't found anywhere (caller decides whether
    that's fatal).

    Args:
        name: env var name (e.g. ``"KIMI_API_KEY"``)
        env_file_path: explicit .env path; defaults to project lookup
            via :func:`default_env_path`.
        prefer_dpapi: when True, check DPAPI BEFORE .env (legacy
            Windows-operator flow).  Default False: env > .env > DPAPI.
    """
    # 1. Explicit OS env var ALWAYS wins (CI / shell exports / Docker)
    env_val = os.environ.get(name)
    if env_val:
        return env_val

    # When prefer_dpapi=True, check DPAPI before .env (legacy flow)
    if prefer_dpapi:
        dpapi_val = _try_dpapi(name)
        if dpapi_val is not None:
            return dpapi_val

    # 2. .env file
    path = env_file_path if env_file_path is not None else default_env_path()
    file_val = env_file.get_key(name, path)
    if file_val:
        return file_val

    # 3. DPAPI fallback (Windows only; quietly skipped elsewhere)
    if not prefer_dpapi:
        dpapi_val = _try_dpapi(name)
        if dpapi_val is not None:
            return dpapi_val

    return None


def _try_dpapi(name: str) -> str | None:
    """Read from DPAPI; return None on any failure (incl. non-Windows
    NotImplementedError).  Never raises."""
    if sys.platform != "win32":
        return None
    try:
        from harness.secrets import dpapi
        if dpapi.has_secret(name):
            return dpapi.decrypt_secret(name)
    except (NotImplementedError, OSError, Exception):
        # Best-effort: any DPAPI error treated as "secret unavailable
        # via DPAPI"; caller falls through to the next path.
        # W9-SILENT-EXCEPTION-AUDIT exception: this site intentionally
        # swallows because DPAPI failure is one of three secret sources
        # the caller is iterating over.
        pass
    return None


def is_set(name: str, *,
           env_file_path: Path | None = None,
           prefer_dpapi: bool = False) -> bool:
    """Return True iff *name* resolves to a non-empty value."""
    return bool(resolve_key(name, env_file_path=env_file_path,
                             prefer_dpapi=prefer_dpapi))


def source_of(name: str, *,
              env_file_path: Path | None = None) -> str:
    """Return a short string naming where *name* would be resolved from.

    Returns one of: "env", "dotenv", "dpapi", "missing".  Useful for the
    `harness env` UI surface showing source per key.
    """
    if os.environ.get(name):
        return "env"
    path = env_file_path if env_file_path is not None else default_env_path()
    if env_file.get_key(name, path):
        return "dotenv"
    if sys.platform == "win32" and _try_dpapi(name) is not None:
        return "dpapi"
    return "missing"
