"""W14-KIMI-CLI-TIER2 2026-05-29: agentic Kimi worker via the Kimi CLI.

The 2026-05-29 Kimi/MiMo doc review + live verification established that
Kimi's full agentic capability — multi-step tool use, web research
(``FetchURL`` / ``SearchWeb``) and PARALLEL SUBAGENTS — is delivered by the
**Kimi CLI itself** (a recognized coding agent that the operator's Kimi Code
subscription key authenticates).  A Code-subscription key CANNOT reach the raw
``/v1`` API (it is User-Agent-gated to coding agents — verified: the endpoint
returns *"Kimi For Coding is currently only available for Coding Agents such
as Kimi CLI, Claude Code, Roo Code…"*).  So the CLI is the ONLY path to
agentic Kimi for this key type — and it is a complete agent in its own right
(subagent fan-out via its ``Agent`` tool with ``max_running_tasks`` self-
management, MCP, skills, hooks).  Verified live: a single ``kimi`` invocation
deployed 6 parallel research subagents, each doing real ``FetchURL`` web
research, and synthesized the results.

This engine dispatches into that CLI headlessly::

    kimi --print --output-format text --final-message-only -w <dir> -p "<prompt>"

- ``--print`` is non-interactive and implicitly enables ``--yolo``
  (auto-approve), so the agent runs unattended.
- ``--final-message-only`` makes **stdout the clean final answer** (verified:
  stdout carried exactly the requested text; the "resume session" hint goes to
  stderr).
- The CLI internally owns the agent loop, subagent orchestration, and tool
  execution — this engine just dispatches and captures the result, making
  agentic Kimi a composable cross-vendor worker alongside DeepSeek / MiMo.

Auth: ``KIMI_API_KEY`` is injected into the subprocess env.  ``get_engine``
resolves it LIVE (P16 ``prefer_live_user``) so a rotated key is used without a
session restart AND the stale ``~/.kimi`` config key (which 401s) is
overridden by the env var (the CLI's documented precedence).

SAFETY: ``--print`` auto-approves ALL actions (Shell / WriteFile included).
This engine therefore defaults to an ISOLATED temp working directory so an
agentic run can't mutate the operator's project unless a ``work_dir`` is
explicitly supplied.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from harness.engines.base import Engine, EngineResponse

_DEFAULT_TIMEOUT_S = 600  # agentic research with subagents can take minutes


def _resolve_kimi_cli_binary() -> str:
    """Locate the ``kimi`` CLI binary.

    Order: explicit ``HARNESS_KIMI_CLI_BINARY`` env override → ``kimi`` on
    PATH → the common off-PATH install location (``~/.local/bin``, where
    ``uv tool install kimi-cli`` puts it) → bare ``kimi`` (resolved at spawn).
    """
    explicit = os.environ.get("HARNESS_KIMI_CLI_BINARY")
    if explicit:
        return explicit
    on_path = shutil.which("kimi")
    if on_path:
        return on_path
    home = Path.home()
    for cand in (home / ".local" / "bin" / "kimi.exe",
                 home / ".local" / "bin" / "kimi"):
        if cand.exists():
            return str(cand)
    return "kimi"


class KimiCliEngine(Engine):
    """Dispatch an agentic task to the local Kimi CLI (Tier 2).

    Honoured ``extra_args``:
      - ``timeout_s`` (int) — subprocess timeout, default 600.
      - ``work_dir`` (str) — working directory for the agent.  Default: a
        fresh isolated temp dir (see SAFETY note in the module docstring).
      - ``model`` / ``extra_args['model']`` — passed as ``-m``; default is
        the CLI's configured default model (``kimi-for-coding``).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        binary: Optional[str] = None,
        default_model: str = "",
        timeout_s: Optional[int] = None,
        verify_binary: bool = True,
    ) -> None:
        super().__init__(api_key=api_key)
        self._binary = binary or _resolve_kimi_cli_binary()
        self._default_model = default_model
        self._timeout_s = timeout_s if timeout_s is not None else _DEFAULT_TIMEOUT_S
        if verify_binary and not (
            os.path.isabs(self._binary) and Path(self._binary).exists()
        ) and shutil.which(self._binary) is None and self._binary != "kimi":
            # Non-fatal: stash a diagnostic; dispatch surfaces it.
            self._binary_error: Optional[str] = (
                f"kimi CLI binary {self._binary!r} not found"
            )
        else:
            self._binary_error = None

    @property
    def name(self) -> str:
        return "kimi-cli"

    def _build_command(self, prompt: str, model: str, work_dir: str) -> list[str]:
        cmd = [
            self._binary,
            "--print",                      # non-interactive (implicit --yolo)
            "--output-format", "text",
            "--final-message-only",         # stdout = clean final answer
            "-w", work_dir,
        ]
        chosen = model or self._default_model
        # Treat engine-name / placeholder values as "use the CLI default".
        if chosen and chosen.strip().lower() not in {"kimi-cli", "kimi", "default", "auto"}:
            cmd += ["-m", chosen]
        cmd += ["-p", prompt]
        return cmd

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Inject the (live-resolved) key so the CLI overrides its possibly
        # stale ~/.kimi config key.  Only set when we actually have one.
        if self._api_key:
            env["KIMI_API_KEY"] = self._api_key
        return env

    def dispatch(
        self,
        packet_content: str,
        model: str,
        extra_args: Optional[dict] = None,
    ) -> EngineResponse:
        extra = extra_args or {}
        if self._binary_error:
            return EngineResponse(
                success=False, text="", latency_ms=0,
                error=self._binary_error,
            )

        work_dir = extra.get("work_dir") or tempfile.mkdtemp(prefix="kimi-cli-")
        timeout = float(extra.get("timeout_s", self._timeout_s))
        cmd = self._build_command(packet_content, model, work_dir)
        env = self._build_env()

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                cwd=work_dir,
            )
        except subprocess.TimeoutExpired:
            return EngineResponse(
                success=False, text="",
                latency_ms=int((time.monotonic() - start) * 1000),
                error=f"kimi-cli subprocess timeout after {timeout}s",
            )
        except FileNotFoundError as exc:
            return EngineResponse(
                success=False, text="", latency_ms=0,
                error=f"kimi CLI binary not found: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - surface, never raise
            return EngineResponse(
                success=False, text="",
                latency_ms=int((time.monotonic() - start) * 1000),
                error=f"kimi-cli dispatch error: {type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - start) * 1000)
        text = (proc.stdout or "").strip()
        if proc.returncode == 0 and text:
            return EngineResponse(
                success=True, text=text, latency_ms=latency_ms, error=None,
            )
        stderr = (proc.stderr or "").strip()
        return EngineResponse(
            success=False, text=text, latency_ms=latency_ms,
            error=(f"kimi-cli exit {proc.returncode}; "
                   f"stderr: {stderr[:300] if stderr else '(empty)'}"),
        )
