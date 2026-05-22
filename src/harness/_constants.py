"""Constants — single source of truth for engine names, env vars, file paths.

Prevents the duplicate-source-of-truth drift flagged in the v1.2 security audit
(cross-cutting requirements, see spec/v1.2-security-amendments.md §3).
"""

from pathlib import Path
from typing import Final

SUPPORTED_BACKENDS: Final = ["deepseek", "kimi", "anthropic", "gemini", "mimo", "mock"]

API_KEY_ENV_VARS: Final = {
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "KIMI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    # Xiaomi MiMo Open Platform (added 2026-05-22, WIRE-MIMO).  Key prefix
    # selects endpoint at dispatch time: ``sk-...`` → pay-as-you-go,
    # ``tp-...`` → Token Plan subscription (treated as zero-cost in budget).
    "mimo": "MIMO_API_KEY",
}

DASHBOARD_PORT: Final = 7878
DASHBOARD_BIND_ADDRESS: Final = "127.0.0.1"
DASHBOARD_TOKEN_FILE: Final = "dashboard.token"

DPAPI_FILE_NAME: Final = "secrets.dpapi"
DB_FILE_NAME: Final = "history.db"

TASK_NAME_PREFIX: Final = "xaxiu-harness-"

LIMIT_MAX: Final = 1000
PROJECT_NAME_REGEX: Final = r"^[a-z0-9-]{1,32}$"

# Repo-relative state directory. _constants.py lives at src/harness/_constants.py
# → parents[2] = repo root. In v1.x installer mode this switches to
# %APPDATA%/xaxiu-harness/state — addressed when the installer ships.
_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
STATE_DIR: Final = _REPO_ROOT / "state"
