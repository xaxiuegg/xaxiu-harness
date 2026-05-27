"""harness doctor — preflight diagnostics for fresh-clone onboarding.

Each check returns a Diagnosis with severity ("ok" | "warn" | "fail") +
short message + optional fix hint.  Output is plain text, color-coded:
green ✓ for ok, yellow ⚠ for warn, red ✗ for fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Diagnosis:
    name: str
    severity: str  # ok | warn | fail
    message: str
    fix: str = ""


def _check_git() -> Diagnosis:
    if shutil.which("git") is None:
        return Diagnosis("git", "fail", "git is not on PATH",
                         "Install Git for Windows from https://git-scm.com/")
    try:
        out = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True, text=True, timeout=5,
        )
        if not out.stdout.strip():
            return Diagnosis("git", "warn", "git user.email not set",
                             "Run: git config --global user.email you@example.com")
    except Exception as exc:
        return Diagnosis("git", "warn", f"git probe failed: {exc}")
    return Diagnosis("git", "ok", "git installed + identity set")


def _check_python_version() -> Diagnosis:
    v = sys.version_info
    if v < (3, 11):
        return Diagnosis("python", "fail",
                         f"Python {v.major}.{v.minor} too old (need ≥3.11)",
                         "Install Python 3.11+ from python.org")
    return Diagnosis("python", "ok", f"Python {v.major}.{v.minor} OK")


def _check_dpapi() -> Diagnosis:
    if sys.platform != "win32":
        return Diagnosis("dpapi", "warn", "DPAPI is Windows-only — secrets store unavailable here")
    try:
        from harness.secrets import dpapi
        # Probe a non-existent secret to exercise read path
        _ = dpapi.list_secrets()
        return Diagnosis("dpapi", "ok", "DPAPI read works")
    except Exception as exc:
        return Diagnosis("dpapi", "fail", f"DPAPI unreadable: {exc}",
                         "Run `harness install` to seed the secrets store")


# ---------------------------------------------------------------------------
# P2 audit fix (2026-05-27): the pre-audit doctor had THREE near-duplicate
# presence checks — _check_secrets, _check_engine_reachability, and
# _check_env_var_inventory.  None of them did a network call, but the one
# named "engine_reachability" promised reachability it never delivered.
# The audit collapsed them into a single _check_engine_keys() PRESENCE
# check; the real reachability path is the new --probe flag, which calls
# probe_engine_live() (the same function keys_ui uses).
# ---------------------------------------------------------------------------

REQUIRED_KEY_VARS: tuple[str, ...] = (
    "KIMI_API_KEY",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "MIMO_API_KEY",
    "OPENAI_API_KEY",
)


def _check_engine_keys() -> Diagnosis:
    """Single presence check for engine API keys (DPAPI + env).

    Replaces the pre-P2 triplet:
        _check_secrets / _check_engine_reachability / _check_env_var_inventory

    Reports ``fail`` if NO key is configured, ``ok`` otherwise.  The
    message carries a full per-key inventory (DPAPI / ENV / UNSET) plus
    the MiMo Token-Plan / PAYG hint that used to live in the (misnamed)
    reachability check.  The fix-hint tells the operator to run
    ``harness doctor --probe`` if they want network validation.
    """
    required = set(REQUIRED_KEY_VARS) - {"OPENAI_API_KEY"}
    try:
        from harness.secrets import dpapi
        dpapi_names = set(dpapi.list_secrets()) & required
    except Exception:
        dpapi_names = set()
    env_names = {k for k in required if os.environ.get(k)}

    # Per-key inventory line: every required key, with its source tag.
    parts = []
    for k in REQUIRED_KEY_VARS:
        if k in dpapi_names:
            parts.append(f"{k}:DPAPI")
        elif os.environ.get(k):
            parts.append(f"{k}:ENV")
        else:
            parts.append(f"{k}:UNSET")
    inventory = ", ".join(parts)

    if not dpapi_names and not env_names:
        return Diagnosis(
            "engine_keys", "fail",
            f"no engine API keys configured ({inventory})",
            "Run `harness keys serve` to add at least one key via the "
            "browser form, or set DEEPSEEK_API_KEY / KIMI_API_KEY / "
            "MIMO_API_KEY env vars.",
        )

    # MiMo type tag (tp- = Token Plan subscription, sk- = pay-as-you-go).
    # Never leak the actual key — only the 3-char prefix branches.
    mimo_key = os.environ.get("MIMO_API_KEY", "")
    mimo_tag = ""
    if mimo_key.startswith("tp-"):
        mimo_tag = " | mimo=tokenplan"
    elif mimo_key.startswith("sk-"):
        mimo_tag = " | mimo=payg"

    return Diagnosis(
        "engine_keys", "ok",
        f"{inventory}{mimo_tag} (run `harness doctor --probe` for live "
        "network validation)",
    )


# ---------------------------------------------------------------------------
# Live network probe (opt-in; --probe flag)
# ---------------------------------------------------------------------------


# Required-var → engine name for probe_engine_live().  Anthropic + Gemini
# are intentionally excluded for now because most operators reach them via
# Pattern B subprocess wrappers (kimi-via-claude / etc.), not the direct
# httpx engines; auto-probing the direct path on a Pattern-B key would
# misleadingly flag the engine "down" when it's actually fine.
_PROBEABLE_ENGINES: dict[str, str] = {
    "KIMI_API_KEY": "kimi",
    "DEEPSEEK_API_KEY": "deepseek",
    "MIMO_API_KEY": "mimo",
}


def _probe_engines_live() -> list[Diagnosis]:
    """Run probe_engine_live() for each provider with a key configured.

    Returns one Diagnosis per probed engine (or one ``warn`` if nothing
    is configured to probe).  Each probe does a real ~5-token dispatch
    via the same code path keys_ui uses (W14-PATTERN-B-* circuit), so a
    typo'd / expired / quota-exhausted key shows up as fail here.

    Excluded from default ``doctor`` runs (slow + costs a few cents);
    surfaced only when the operator passes ``--probe``.
    """
    from harness.cli_helpers import probe_engine_live  # lazy: heavy import

    required = set(_PROBEABLE_ENGINES) & set(REQUIRED_KEY_VARS)
    try:
        from harness.secrets import dpapi
        dpapi_names = set(dpapi.list_secrets()) & required
    except Exception:
        dpapi_names = set()
    env_names = {k for k in required if os.environ.get(k)}
    configured = sorted(dpapi_names | env_names)

    if not configured:
        return [Diagnosis(
            "engine_probe", "warn",
            "no probeable keys configured (kimi/deepseek/mimo) — "
            "nothing to probe",
            "Configure at least one provider key, then re-run "
            "`harness doctor --probe`.",
        )]

    results: list[Diagnosis] = []
    for var in configured:
        engine = _PROBEABLE_ENGINES[var]
        try:
            category, err = probe_engine_live(engine, log=False)
        except Exception as exc:
            results.append(Diagnosis(
                f"probe:{engine}", "fail",
                f"{engine} probe crashed: "
                f"{type(exc).__name__}: {str(exc)[:120]}",
                f"Re-check the {var} value (DPAPI store or .env).",
            ))
            continue
        if category == "up":
            results.append(Diagnosis(
                f"probe:{engine}", "ok",
                f"{engine} live probe OK",
            ))
        else:
            err_snip = (err or "")[:120].replace("\n", " ")
            results.append(Diagnosis(
                f"probe:{engine}", "fail",
                f"{engine} probe failed (category={category}): {err_snip}",
                f"Re-check the {var} value or run "
                f"`harness keys serve` to rotate.",
            ))
    return results


def _check_coord_writable() -> Diagnosis:
    try:
        coord = Path("coord")
        coord.mkdir(exist_ok=True)
        probe = coord / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Diagnosis("coord_dir", "ok", "coord/ is writable")
    except Exception as exc:
        return Diagnosis("coord_dir", "fail", f"can't write to coord/: {exc}",
                         "Check filesystem permissions on the project dir")


def _check_claude_binary() -> Diagnosis:
    """W14-DEPLOY-FRICTION 2026-05-26: surface whether the ``claude``
    CLI is installed.  Required by all Pattern B engines
    (kimi-via-claude / mimo-via-claude / deepseek-via-claude) AND
    by the wrapper scripts (claude-mimo / claude-kimi / etc.).

    Without this check, operators who skipped the Claude Code install
    step in OPERATOR_QUICKSTART.md hit silent subprocess failures on
    their first dispatch and have to debug from the error message
    instead of from doctor's actionable hint.

    Severity: WARN, not FAIL — the operator may legitimately be
    running harness in a context where Pattern B isn't needed (CI
    smoke, swarm-only workflow, etc.).
    """
    binary = shutil.which("claude")
    if binary is None:
        return Diagnosis(
            "claude_binary", "warn",
            "claude CLI not found on PATH — Pattern B engines + "
            "wrapper scripts will not work",
            "Install Claude Code from "
            "https://docs.claude.com/en/docs/claude-code/setup, "
            "then verify with `claude --version`.",
        )
    # Optionally probe version + auth state without blocking
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        version_info = (out.stdout or "").strip().split("\n")[0]
    except Exception as exc:
        return Diagnosis(
            "claude_binary", "warn",
            f"claude found at {binary} but --version failed: {exc}",
            "Try `claude doctor` to diagnose the install.",
        )
    return Diagnosis(
        "claude_binary", "ok",
        f"claude installed: {version_info or binary}",
    )


def _check_task_scheduler() -> Diagnosis:
    if sys.platform != "win32":
        return Diagnosis("task_scheduler", "warn", "Windows-only — skipped")
    if shutil.which("schtasks") is None and shutil.which("powershell") is None:
        return Diagnosis("task_scheduler", "fail", "neither schtasks nor PowerShell on PATH")
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/FO", "LIST"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return Diagnosis("task_scheduler", "warn",
                             "schtasks query failed — may need admin / scope")
        return Diagnosis("task_scheduler", "ok", "Task Scheduler reachable")
    except Exception as exc:
        return Diagnosis("task_scheduler", "warn", f"task scheduler probe error: {exc}")


def run_all(with_probe: bool = False) -> list[Diagnosis]:
    """Run every check and return the list of Diagnoses.

    Args:
        with_probe: when True, append live network probes against each
            provider with a configured key (real ~5-token round-trips).
            Default False — probes are slow (several seconds per engine)
            and cost a few cents per run.  Surfaced via ``harness doctor
            --probe`` (P2 audit fix 2026-05-27).
    """
    diags = [
        _check_python_version(),
        _check_git(),
        _check_claude_binary(),  # W14-DEPLOY-FRICTION: required by Pattern B
        _check_dpapi(),
        _check_engine_keys(),    # P2: consolidated presence check
        _check_coord_writable(),
        _check_task_scheduler(),
    ]
    if with_probe:
        diags.extend(_probe_engines_live())
    return diags


def overall_severity(diagnoses: list[Diagnosis]) -> str:
    """Return the most-severe severity across all diagnoses."""
    if any(d.severity == "fail" for d in diagnoses):
        return "fail"
    if any(d.severity == "warn" for d in diagnoses):
        return "warn"
    return "ok"
