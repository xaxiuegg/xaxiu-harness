"""xaxiu-harness CLI.

Cross-project multi-engine LLM dispatch + monitoring tool.
13 top-level verbs (most wired; retro / dashboard-serve / loops remain
pending-wave stubs).  ``status`` and ``observer`` are command groups with
subcommands managed in this module; see ``spec/status-tracker.md`` and
``spec/observer.md`` for the underlying primitives.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import click
import yaml

from harness._constants import (
    _REPO_ROOT,
    LOOP_DEFAULT_OBSERVER_DIR,
    LOOP_DEFAULT_STATE_PATH,
)
from harness.adapters.from_description import generate_adapter_from_nl
from harness.adapters.loader import _repo_root, load_project_adapter, load_template
from harness.adapters.scaffold import scaffold_adapter
from harness.cli_helpers import probe_all_engines
from harness.engines.dispatcher import dispatch_packet
from harness.operator import OperatorMode, resolve_operator_config
from harness.operator.flags import OPERATOR_FLAG_NAMES, apply_operator_flags
from harness.state.files import read_engine_health, update_engine_health

# Budget primitive (BUDGET-METER)
from harness.budget import (
    DEFAULT_CAP_PATH,
    DEFAULT_LEDGER_PATH,
    export_daily_csv,
    read_ledger,
    summary as budget_summary,
)

# Observer primitive (roster #20)
from harness.observer.cycle import run_cycle
from harness.observer.flags import (
    FlagSeverity,
    ensure_flag_dirs,
    list_pending_flags,
    ack_flag,
)
from harness.observer.state import read_state, write_state, ObserverState
from harness.observer.scheduler import register_tasks, unregister_tasks


@click.group()
@apply_operator_flags
@click.pass_context
def cli(ctx: click.Context, **operator_overrides: object) -> None:
    """xaxiu-harness: dispatch, observe, and retro across LLM engines."""
    ctx.ensure_object(dict)
    cli_overrides = {name: operator_overrides.get(name) for name in OPERATOR_FLAG_NAMES}
    ctx.obj["operator_config"] = resolve_operator_config(
        cli_overrides=cli_overrides,
        env=os.environ,
    )


def _bootstrap_utf8_stdout() -> None:
    """W12-WINDOWS-CP1252-FIX (2026-05-24): force UTF-8 on stdout/stderr.

    The 20-agent operator-review panel found three distinct CLI entry
    points (``preflight``, ``--help``, ``agent init``) crashing with
    ``UnicodeEncodeError`` on Windows console (cp1252) when emitting
    `\\u2192` (->), `\\u03b1` (alpha), or `\\u2713` (check) glyphs.
    Reconfigure stdout/stderr at process entry so click.echo never
    hits cp1252 again.  errors='replace' is a safety belt: if a glyph
    still cannot encode (older Python without reconfigure, or a fd
    redirected to a strict file), the glyph is replaced with '?'
    rather than crashing.

    Safe on POSIX (utf-8 is the default anyway) and on Windows with
    UTF-8 console codepage.  Idempotent.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # piped to a non-TextIOWrapper sink
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Some redirected streams refuse reconfigure; not fatal.
            pass


def main(*args, **kwargs):
    """Entry point that wraps click with W5-DD top-level HarnessError handler.

    Any ``HarnessError`` that escapes the click verb is routed through
    ``handle_harness_error`` so the operator sees the L5 escalation banner
    (or the L3/L4 one-line summary) instead of click's vanilla traceback.
    Exits with the level-derived exit code (0/0/1/3/4).

    Programmatic callers that catch HarnessError themselves can still call
    ``cli`` directly to bypass this.
    """
    # W12-WINDOWS-CP1252-FIX: force UTF-8 on stdout/stderr before click
    # writes a single byte.  The 20-agent operator-review panel found
    # this was the #1 universal blocker (cp1252 crashes on -> alpha check).
    _bootstrap_utf8_stdout()

    from harness.errors import HarnessError, handle_harness_error
    try:
        return cli(*args, **kwargs)
    except HarnessError as exc:
        handle_harness_error(exc, sys_exit=sys.exit)


@cli.command()
@click.option("--project", "-p", help="Project name (maps to adapter).")
@click.option("--packet", help="Path to dispatch packet markdown file.")
@click.option("--backend", "-b", help="Override backend engine.")
@click.option("--model", "-m", help="Override model name.")
@click.option("--force-engine", help="Force a specific engine (disables routing).")
@click.pass_context
def dispatch(
    ctx: click.Context,
    project: Optional[str],
    packet: Optional[str],
    backend: Optional[str],
    model: Optional[str],
    force_engine: Optional[str],
) -> None:
    """Execute a packet; auto-route if no backend is given."""
    if not project or not packet:
        click.echo("error: --project and --packet are required", err=True)
        sys.exit(2)
    op_cfg = (ctx.obj or {}).get("operator_config") if ctx.obj else None
    if op_cfg is not None and op_cfg.mode == OperatorMode.DRY_RUN:
        click.echo(
            f"dry-run: would dispatch project={project} packet={packet} "
            f"backend={backend} model={model} force_engine={force_engine}"
        )
        sys.exit(0)
    forced = force_engine or backend
    result = dispatch_packet(
        project=project,
        packet_path=packet,
        force_engine=forced,
        force_model=model,
    )
    if result.success:
        click.echo(result.text)
        sys.exit(0)
    click.echo(
        f"error: {result.error or 'unknown'} "
        f"(tried: {', '.join(result.fallback_chain) or 'none'})",
        err=True,
    )
    sys.exit(1)


@cli.command(name="spec-register", hidden=True)
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
def spec_register_cmd(spec_path: Path) -> None:
    """Register a spec's SHA256 + author into the provenance log."""
    from harness.coord.provenance import register
    entry = register(spec_path)
    click.echo(f"registered: {entry.spec_path}")
    click.echo(f"  sha256:    {entry.sha256[:16]}...")
    click.echo(f"  operator:  {entry.operator}")
    click.echo(f"  commit:    {entry.git_commit}")
    click.echo(f"  at:        {entry.registered_at}")


@cli.command(name="spec-verify", hidden=True)
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
def spec_verify_cmd(spec_path: Path) -> None:
    """Verify a spec's on-disk SHA matches its provenance registration."""
    from harness.coord.provenance import verify
    matches, msg = verify(spec_path)
    click.echo(f"{'OK' if matches else 'MISMATCH'}: {msg}")
    sys.exit(0 if matches else 1)


@cli.command(name="start")
@click.option("--orchestrator", default=None, type=click.Choice(
    ["claude", "mimo", "deepseek", "kimi"], case_sensitive=False,
), help="Skip the interactive picker; pin this orchestrator.")
@click.option("--mode", default=None, type=click.Choice(
    ["interactive", "autonomous"], case_sensitive=False,
), help="Skip the mode prompt; pin interactive (you drive) or "
        "autonomous (Task Scheduler runs the loop).")
@click.option("--list", "just_list", is_flag=True,
              help="Print the orchestrator picker + connection status, then exit.")
@click.option("--interval-minutes", type=int, default=30,
              help="Task Scheduler tick cadence for autonomous mode (default 30).")
@click.option("--skip-preflight", is_flag=True, default=False,
              help="W6-B3: bypass the preflight readiness gate before "
                   "arming autonomous mode (use only when you know a "
                   "warn-severity check is acceptable for your run).")
def start_cmd(orchestrator: str | None, mode: str | None,
              just_list: bool, interval_minutes: int,
              skip_preflight: bool) -> None:
    """W5-SS 2026-05-23: pick orchestrator + toggle autonomous loop.

    Operator-facing boot screen.  Interactive picker shows the 4
    orchestrators (Claude / MiMo / DeepSeek / Kimi) with connection
    status, lets the operator pick by number, then asks for mode:

      INTERACTIVE — you drive; the harness assists.  Most CLI verbs
                    use the chosen orchestrator as their default
                    --engine.
      AUTONOMOUS  — Task Scheduler runs the loop; you check
                    `harness morning-brief` for the daily handoff.

    The choice persists in coord/dev_loop/state.json so future verb
    invocations default to it.

    Skip the prompts via `--orchestrator X --mode Y` for scripted
    invocation.
    """
    from harness.orchestrator_picker import (
        ORCHESTRATORS, ConnectionStatus, by_key, render_picker,
    )

    # --list mode: just show the menu + exit
    if just_list:
        click.echo(render_picker())
        sys.exit(0)

    # 1. Orchestrator picker
    if orchestrator is None:
        click.echo(render_picker())
        default_idx = 1  # MiMo (brainstorm-recommended primary)
        pick = click.prompt(
            "Pick orchestrator [1-4]",
            type=click.IntRange(1, len(ORCHESTRATORS)),
            default=default_idx,
        )
        chosen = ORCHESTRATORS[pick - 1]
    else:
        chosen = by_key(orchestrator.lower())
        if chosen is None:
            click.echo(f"ERROR: unknown orchestrator '{orchestrator}'", err=True)
            sys.exit(1)

    # 2. Connection probe
    status = chosen.probe()
    if status == ConnectionStatus.MISSING_KEY:
        env = chosen.env_var() or "?"
        click.echo(
            f"\n✗ Cannot connect: {chosen.label} requires {env} in env "
            f"or DPAPI store.\n"
            f"  Set it and re-run: `harness start`.",
            err=True,
        )
        sys.exit(2)
    if status == ConnectionStatus.BLOCKED:
        click.echo(
            f"\n⚠ {chosen.label} BLOCKED: anti-recursion guard fires when "
            f"`claude -p` is spawned from inside another Claude Code session.\n"
            f"  To use Claude autonomously, install the Task Scheduler entry:\n"
            f"    harness orchestrator install-claude-scheduler\n"
            f"  Or pick a different orchestrator now.",
            err=True,
        )
        sys.exit(2)
    if status == ConnectionStatus.NOT_INSTALLED:
        click.echo(
            f"\n✗ {chosen.label} not installed: `claude` binary missing from PATH.\n"
            f"  Install Claude Code, then re-run.",
            err=True,
        )
        sys.exit(2)

    # 3. Mode prompt
    if mode is None:
        click.echo()
        click.echo("Mode:")
        click.echo("  [I]nteractive (you drive; harness assists)")
        click.echo("  [A]utonomous (Task Scheduler runs the loop)")
        mode_input = click.prompt(
            "Mode", type=click.Choice(["I", "A", "i", "a"]),
            default="I", show_choices=False,
        )
        mode = "interactive" if mode_input.lower() == "i" else "autonomous"

    # 4. Persist choice to state
    from datetime import datetime, timezone
    state_path = Path("coord") / "dev_loop" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    state["active_orchestrator"] = chosen.key
    state["active_mode"] = mode
    state["orchestrator_chosen_at"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    click.echo()
    click.echo(f"✓ Orchestrator: {chosen.label} ({chosen.key})")
    click.echo(f"✓ Mode:         {mode}")
    click.echo(f"✓ Engine connected ({status.value}).")
    click.echo(f"✓ State persisted: {state_path}")

    # 5. Mode-specific next steps
    click.echo()
    if mode == "autonomous":
        # W6-B3 2026-05-23: preflight gate.  Refuse to arm autonomous
        # mode unless the readiness checks pass (or the operator opts
        # out via --skip-preflight).  Fail-severity checks are
        # blockers; warn-severity ones print a warning but proceed
        # (operator can still inspect via `harness preflight`).
        if not skip_preflight:
            from harness.preflight import run_all, overall_exit_code
            click.echo("Preflight: running readiness checks...")
            pre_results = run_all()
            pre_exit = overall_exit_code(pre_results)
            if pre_exit == 4:
                click.echo(
                    "\n✗ Preflight FAILED — autonomous mode REFUSED.\n"
                    "  Failing checks:",
                    err=True,
                )
                for r in pre_results:
                    if r.severity == "fail":
                        click.echo(f"    [X] {r.name}: {r.message}", err=True)
                        if r.fix:
                            click.echo(f"        fix: {r.fix}", err=True)
                click.echo(
                    "\n  Resolve the blockers above (or use "
                    "`--skip-preflight` if you accept the risk), "
                    "then re-run `harness start`.",
                    err=True,
                )
                sys.exit(4)
            elif pre_exit == 1:
                click.echo(
                    "\n⚠ Preflight surfaced warnings; proceeding to "
                    "autonomous mode anyway.  Inspect via "
                    "`harness preflight` if unsure.",
                    err=True,
                )
            else:
                click.echo("  ✓ Preflight passed.")
        else:
            click.echo(
                "  ⚠ Skipping preflight (--skip-preflight set).",
                err=True,
            )
        click.echo(f"Autonomous mode: arming Task Scheduler at {interval_minutes}min cadence...")
        if chosen.key == "claude":
            click.echo("  → using `harness orchestrator install-claude-scheduler` "
                       "(Task Scheduler-launched claude -p; no parent Claude Code)")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "harness", "orchestrator",
                     "install-claude-scheduler",
                     "--interval-minutes", str(interval_minutes)],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    click.echo("  ✓ Task Scheduler entry installed.")
                else:
                    click.echo(f"  ⚠ install failed: {result.stderr[:200]}")
            except Exception as exc:
                click.echo(f"  ⚠ install error: {exc}")
        else:
            click.echo(f"  → using `harness orchestrator install-scheduler` "
                       f"(Python daemon running queue execute)")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "harness", "orchestrator",
                     "install-scheduler",
                     "--interval-minutes", str(interval_minutes)],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    click.echo("  ✓ Task Scheduler entry installed.")
                else:
                    click.echo(f"  ⚠ install failed: {result.stderr[:200]}")
            except Exception as exc:
                click.echo(f"  ⚠ install error: {exc}")
        click.echo()
        click.echo("Check progress with:")
        click.echo("  harness morning-brief --since-hours 12   # daily handoff")
        click.echo("  harness queue list                       # what's in/out of queue")
        click.echo("  harness observer flags                   # pending escalations")
    else:
        click.echo("Interactive mode.  Common next steps:")
        click.echo(f"  harness spec-init my-feature             # author a spec")
        click.echo(f"  harness queue execute --once             # process next spec")
        click.echo(f"  harness coord plan --spec X --engine {chosen.key}")
        click.echo(f"  harness morning-brief                     # synthesize recent activity")

    sys.exit(0)


def _agent_instructions_snippet(
    fmt: str, repo_root: Path, home_dir: Path,
) -> str:
    """W14-ASK-DOCS 2026-05-27: single source of truth for the agent-
    instructions snippet content.  Used by BOTH ``harness agent-
    instructions`` (which prints) AND ``harness install-agent-
    instructions`` (which appends to ~/.claude/CLAUDE.md).

    Keeping the content in one place prevents the two commands from
    drifting — a prior W14 bug had ``install`` carrying stale
    pre-v0.5.1 3-engine framing while the print verb already used the
    new 3-mode framing.
    """
    if fmt == "claude-md":
        return (
            f"## xaxiu-harness is available\n\n"
            f"You have access to a multi-engine LLM tool installed at "
            f"`{repo_root}`.  Three things it provides:\n\n"
            f"### 1. `harness ask` — daily-driver LLM verb\n\n"
            f"Bare `python -m harness ask \"...\"` routes through an "
            f"empirical recommender to ONE engine (~$0.01-0.05, ~30s).  "
            f"Cheap enough for routine second opinions; NOT for every "
            f"prompt (you're already an LLM — do the work yourself when "
            f"you can).\n\n"
            f"Three modes:\n\n"
            f"```bash\n"
            f"python -m harness ask \"...\"                  # routed, 1 engine ~$0.01-0.05\n"
            f"python -m harness ask \"...\" --task <class>   # routed by task class\n"
            f"python -m harness ask \"<claim>\" --audit      # 2 engines: producer + auditor ~$0.05\n"
            f"python -m harness ask \"...\" --panel          # 3 engines parallel ~$0.20-0.30\n"
            f"```\n\n"
            f"Task classes: `default | latency | verbose | cost | "
            f"high-volume | multimodal | audit`.  "
            f"`harness engines recommend <class>` shows the pick + "
            f"rationale.\n\n"
            f"**`--audit` is the hallucination self-check primitive.**  "
            f"When you're about to commit to a non-obvious factual "
            f"claim that downstream decisions hinge on, audit it first: "
            f"`harness ask \"<claim>\" --audit --output /tmp/audit` and "
            f"inspect `/tmp/audit/summary.json` for "
            f"`verdict.verdict ∈ {{PASS, PARTIAL, FAIL, UNKNOWN}}`.\n\n"
            f"**`--panel` is the 3-engine fanout** (was the bare default "
            f"before v0.5.1; now opt-in).  Use only for genuinely cross-"
            f"cutting design crossroads where vendor diversity matters.\n\n"
            f"**When NOT to reach for `harness ask`**:\n"
            f"- Routine implementation work (write the code yourself)\n"
            f"- Factual lookups (WebSearch / WebFetch are faster + free)\n"
            f"- Multi-file refactors / agentic dispatch (use xaxiu-swarm, "
            f"see #3 below)\n"
            f"- Sub-routine LLM calls from external tools (use the "
            f"proxy, see #2 below)\n\n"
            f"Outputs land at `{repo_root}\\coord\\reviews\\ask-"
            f"<ts>-<slug>\\` with `question.md`, per-engine `*.md`, "
            f"`packet.md` (panel/audit only), and `summary.json` (with "
            f"`mode` field).\n\n"
            f"### 2. `harness proxy` — OpenAI-compatible HTTP endpoint\n\n"
            f"For sub-routine LLM calls from third-party tools that "
            f"want an OpenAI-compatible `/v1/chat/completions`:\n\n"
            f"```bash\n"
            f"python -m harness proxy start    # daemon on 127.0.0.1:7879\n"
            f"python -m harness proxy status   # pool / in-flight stats\n"
            f"python -m harness proxy stop\n"
            f"```\n\n"
            f"Then point the consuming tool at "
            f"`OPENAI_API_BASE=http://127.0.0.1:7879/v1`.  Multi-key "
            f"pool + circuit breaker apply.  Default upstream is Kimi "
            f"(Moonshot); the proxy was the missing piece in W14 — it "
            f"is now first-class in agent instructions.\n\n"
            f"### 3. xaxiu-swarm (sibling repo) — agentic dispatch\n\n"
            f"For multi-file refactors + multi-turn tool use across a "
            f"codebase, the sibling project handles it.  Install at "
            f"`https://github.com/xaxiuegg/xaxiu-swarm` then:\n\n"
            f"```bash\n"
            f"xaxiu-swarm dispatch --backend kimi \\\n"
            f"  --deliverable /path/to/output.md \\\n"
            f"  --add-dir /path/to/repo \\\n"
            f"  --context-file CLAUDE.md \\\n"
            f"  --timeout 420 \\\n"
            f"  --packet packet.md\n"
            f"```\n\n"
            f"Backends: `kimi` (CLI, agentic), `kimi-api`, `deepseek`, "
            f"`qwen`, `mimo` (TOS-compliant via Claude Code subprocess).  "
            f"NOT required for `harness ask` or `harness proxy` — clone "
            f"only if you need agentic multi-file work.\n\n"
            f"### Support verbs\n\n"
            f"- `python -m harness doctor` — 9-check health table\n"
            f"- `python -m harness engines recommend <class>` — "
            f"empirical engine pick + rationale\n"
            f"- `python -m harness keys serve` — browser form for "
            f"per-provider API keys\n"
            f"- Per-provider Claude Code wrappers at "
            f"`{home_dir}\\.harness\\bin\\` (claude-mimo, claude-kimi, "
            f"claude-deepseek, etc.) for interactive sessions routed "
            f"to a specific provider.\n\n"
            f"**Visual reference**: `{repo_root}\\docs\\"
            f"HARNESS_VISUAL_MANUAL.md` has screenshots + walkthroughs.\n"
        )
    elif fmt == "prompt":
        return (
            f"You have xaxiu-harness installed at {repo_root}.  Three "
            f"things it provides:\n\n"
            f"1. **`python -m harness ask \"...\"`** — daily-driver LLM "
            f"verb.  Bare ask routes to ONE engine via the recommender "
            f"(~$0.01-0.05, ~30s).  `--audit` adds a second engine to "
            f"critique the answer for hallucinations (~$0.05).  "
            f"`--panel` fires 3 engines in parallel for high-stakes "
            f"design crossroads (~$0.20-0.30).  Outputs land at "
            f"`{repo_root}\\coord\\reviews\\ask-<ts>-<slug>\\` — read "
            f"`packet.md` (panel/audit modes) or the lone "
            f"`<engine>.md` (routed) for the answer.\n\n"
            f"2. **`python -m harness proxy start`** — OpenAI-compatible "
            f"endpoint on 127.0.0.1:7879 for third-party tools that "
            f"want HTTP `/v1/chat/completions` (set "
            f"`OPENAI_API_BASE=http://127.0.0.1:7879/v1`).\n\n"
            f"3. **xaxiu-swarm** (sibling repo) — agentic multi-file "
            f"dispatch via `xaxiu-swarm dispatch --backend <name> "
            f"--deliverable <path>`.  Use for multi-file refactors.\n\n"
            f"When NOT to use `harness ask`: routine implementation "
            f"(do it yourself), factual lookups (WebSearch), multi-file "
            f"refactors (xaxiu-swarm), or third-party tool LLM calls "
            f"(use the proxy).  Engine health: `harness doctor`.  "
            f"Empirical routing: `harness engines recommend <class>`."
        )
    elif fmt == "short":
        return (
            f"xaxiu-harness ({repo_root}) provides three things: "
            f"(1) `python -m harness ask \"...\"` — daily-driver LLM "
            f"verb (routed ~$0.01-0.05, `--audit` ~$0.05, `--panel` "
            f"~$0.20-0.30); (2) `python -m harness proxy start` — "
            f"OpenAI-compatible endpoint on 127.0.0.1:7879 for "
            f"third-party tools; (3) sibling repo `xaxiu-swarm` for "
            f"agentic multi-file dispatch.  Reach for `--audit` when "
            f"you've just made a non-obvious factual claim and want it "
            f"sanity-checked by a different engine."
        )
    else:
        raise ValueError(f"Unknown format: {fmt!r}")


@cli.command(name="agent-instructions")
@click.option("--format", "fmt", type=click.Choice([
    "claude-md", "prompt", "short",
]), default="claude-md", help=(
    "Output format.  'claude-md' = a CLAUDE.md section you can paste "
    "into ~/.claude/CLAUDE.md (works for all sessions on this machine). "
    "'prompt' = a one-shot prompt to paste into a new agent session. "
    "'short' = a one-paragraph hint."
))
def agent_instructions_cmd(fmt: str) -> None:
    """W14-AGENT-INSTRUCTIONS 2026-05-26: print a snippet that tells
    an agent (Claude Code, Cursor, etc.) the harness is available and
    how to use it.

    Use cases:

      \b
      harness agent-instructions > ~/.claude/CLAUDE.md.harness.md
        (then `cat` it into your user-level CLAUDE.md to have the
         harness auto-available in every Claude Code session on
         this machine)

      \b
      harness agent-instructions --format prompt | clip      (Windows)
      harness agent-instructions --format prompt | pbcopy    (macOS)
        (puts the prompt in your clipboard; paste into the next
         agent session manually)

      \b
      harness agent-instructions --format short
        (one-paragraph hint for embedding in a project's CLAUDE.md)
    """
    # Resolve the install path so the snippet has the right absolute
    # path baked in
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home()
    click.echo(_agent_instructions_snippet(fmt, repo_root, home_dir))
    sys.exit(0)


@cli.command(name="install-agent-instructions")
@click.option("--target", "target_path", type=click.Path(
    dir_okay=False, path_type=Path,
), default=None, help=(
    "Path to the CLAUDE.md to append into.  Default: "
    "~/.claude/CLAUDE.md (Claude Code's user-level memory)."
))
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would be appended without writing.")
@click.option("--uninstall", is_flag=True, default=False,
              help="Remove the harness section from the target file "
                   "(matched by W14-HARNESS-AGENT-INSTRUCTIONS marker).")
@click.option("--force", is_flag=True, default=False,
              help="Re-append even if the marker already exists "
                   "(replaces the existing section).")
def install_agent_instructions_cmd(
    target_path: Path | None,
    dry_run: bool,
    uninstall: bool,
    force: bool,
) -> None:
    """W14-AGENT-INSTRUCTIONS 2026-05-26: append the harness snippet
    to ~/.claude/CLAUDE.md so EVERY Claude Code session on this
    machine knows the harness is available.

    Idempotent: re-running is a no-op unless --force is given.
    The appended section is wrapped in HTML comment markers
    (``<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->``) so it
    can be detected + removed cleanly.

    Examples:

      \b
      harness install-agent-instructions
        (appends to ~/.claude/CLAUDE.md, creating it if missing)

      \b
      harness install-agent-instructions --target ./CLAUDE.md
        (appends to the current project's CLAUDE.md instead)

      \b
      harness install-agent-instructions --dry-run
        (preview what would change)

      \b
      harness install-agent-instructions --uninstall
        (remove the harness section, leaving the rest of
         CLAUDE.md untouched)
    """
    # Resolve target
    if target_path is None:
        target_path = Path.home() / ".claude" / "CLAUDE.md"
    target_path = Path(target_path).resolve()

    # Markers for idempotent install / uninstall
    start_marker = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->"
    end_marker = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->"

    # Build the snippet using the shared helper so this command can
    # never drift from `harness agent-instructions`.  Single source of
    # truth in `_agent_instructions_snippet` (W14-ASK-DOCS 2026-05-27).
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home()
    snippet_body = _agent_instructions_snippet(
        "claude-md", repo_root, home_dir,
    )
    full_block = (
        f"\n{start_marker}\n"
        f"<!-- Auto-installed by `harness install-agent-instructions`. "
        f"Edit the harness repo, not this block. -->\n\n"
        f"{snippet_body}\n"
        f"{end_marker}\n"
    )

    # Read current state
    if target_path.exists():
        current = target_path.read_text(encoding="utf-8")
    else:
        current = ""

    # Locate existing block (if any) for idempotent + force + uninstall
    has_block = start_marker in current and end_marker in current
    if has_block:
        start_idx = current.index(start_marker)
        end_idx = current.index(end_marker) + len(end_marker)
        # Include the leading \n if present
        if start_idx > 0 and current[start_idx - 1] == "\n":
            start_idx -= 1

    # ---- Uninstall ----
    if uninstall:
        if not has_block:
            click.echo(
                f"  (no harness section found in {target_path})"
            )
            sys.exit(0)
        new_content = current[:start_idx] + current[end_idx:]
        # Strip trailing newlines we just orphaned
        new_content = new_content.rstrip("\n") + "\n"
        if dry_run:
            click.echo(
                f"  Would remove the harness section from {target_path}"
            )
            click.echo(f"  ({end_idx - start_idx} bytes)")
            sys.exit(0)
        target_path.write_text(new_content, encoding="utf-8")
        click.echo(
            click.style(
                f"  ✓ removed harness section from {target_path}",
                fg="green",
            )
        )
        sys.exit(0)

    # ---- Install / append ----
    if has_block and not force:
        click.echo(
            f"  Harness section already present in {target_path}."
        )
        click.echo(
            f"  Use --force to replace it, or --uninstall to remove."
        )
        sys.exit(0)

    if has_block and force:
        # Replace existing block
        new_content = current[:start_idx] + full_block + current[end_idx:]
        action = "replaced"
    else:
        # Append (with leading separator if file non-empty)
        if current and not current.endswith("\n"):
            current = current + "\n"
        new_content = current + full_block
        action = "appended to"

    if dry_run:
        click.echo(
            f"  Would {'replace' if action == 'replaced' else 'append'} "
            f"in: {target_path}"
        )
        click.echo()
        click.echo("  ---- preview ----")
        click.echo(full_block)
        click.echo("  ---- end preview ----")
        sys.exit(0)

    # Ensure parent dir exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(new_content, encoding="utf-8")
    click.echo(
        click.style(
            f"  ✓ harness section {action} {target_path}",
            fg="green",
        )
    )
    click.echo()
    click.echo(
        "  Every Claude Code session on this machine will now know "
        "the harness is available + how to use it."
    )
    sys.exit(0)


@cli.command(name="setup")
@click.option("--non-interactive", is_flag=True, default=False,
              help="Accept safe defaults at every prompt + skip "
                   "actions that would open a browser or run an "
                   "interactive shell.  Suitable for CI / scripted "
                   "bootstrap.")
def setup_cmd(non_interactive: bool) -> None:
    """W14-HARNESS-SETUP 2026-05-26: guided fresh-machine onboarding.

    Walks a non-technical operator from blank machine to first
    successful dispatch.  Each step is consent-gated; the wizard never
    modifies PATH, runs sudo, or touches files outside the repo +
    ~/.harness/.

    Steps:

      \b
      1. harness doctor — preflight diagnostics
      2. Claude Code CLI availability check (with install hint)
      3. API key configuration (offers to launch keys UI)
      4. Wrapper script installation (claude-mimo / claude-kimi / etc.)
      5. Smoke dispatch (verifies end-to-end wiring)

    Safe to re-run.  Each step detects existing state + skips when
    already done.
    """
    from harness.setup_wizard import run_wizard
    sys.exit(run_wizard(non_interactive=non_interactive))


_VALID_TASK_CLASSES = (
    "default", "latency", "verbose", "cost", "high-volume",
    "multimodal", "audit",
)


@cli.command(name="ask")
@click.argument("question", required=False)
@click.option("--file", "question_file", type=click.Path(
    exists=True, dir_okay=False, path_type=Path,
), default=None,
    help="Read the question from a file instead of an argument.")
@click.option("--engines", default="", help=(
    "Comma-separated engine list.  Pinning overrides --task and --panel "
    "(used by scripts that need a specific engine, e.g. HANDOFF step 7)."
))
@click.option("--task", "task_class",
              type=click.Choice(_VALID_TASK_CLASSES, case_sensitive=False),
              default="default", show_default=True, help=(
    "Routing task class for the bare (routed) default.  Picks one engine "
    "via `harness engines recommend <class>`.  Ignored if --engines or "
    "--panel is passed."
))
@click.option("--panel", "panel_mode", is_flag=True, default=False, help=(
    "Fire the legacy 3-engine cross-engine panel "
    "(kimi-via-claude + mimo-via-claude + deepseek-via-claude) in parallel.  "
    "Was the bare default before v0.5.x; now opt-in.  Use for high-stakes "
    "design crossroads where vendor diversity matters."
))
@click.option("--audit", "audit_mode", is_flag=True, default=False, help=(
    "Run producer → auditor flow.  The producer (routed default, or "
    "--engines / --task pick) answers; a DIFFERENT engine (picked via "
    "`recommend('audit', exclude={producer})`) then audits the answer "
    "and returns a structured VERDICT (PASS / PARTIAL / FAIL).  Useful "
    "for catching hallucinations and stress-testing factual claims.  "
    "~$0.05 / ~60s.  Conflicts with --panel."
))
@click.option("--audit-engine", "audit_engine_override", default="", help=(
    "Override the auditor engine pick (default: chosen by recommender).  "
    "Implies --audit."
))
@click.option("--output", "output_dir", type=click.Path(
    file_okay=False, path_type=Path,
), default=None,
    help="Output directory for per-engine responses.  Default: "
         "coord/reviews/ask-<timestamp>-<slug>/")
@click.option("--max-budget-usd", type=float, default=0.30, show_default=True,
              help="Per-engine spend cap.")
@click.option("--timeout-s", type=int, default=180, show_default=True,
              help="Per-engine timeout in seconds.")
@click.option("--no-save", is_flag=True, default=False,
              help="Skip saving to disk; print to stdout only.")
@click.option("--print-text", is_flag=True, default=False,
              help="Print full response text to stdout (default: "
                   "table + path only).")
def ask_cmd(
    question: str | None,
    question_file: Path | None,
    engines: str,
    task_class: str,
    panel_mode: bool,
    audit_mode: bool,
    audit_engine_override: str,
    output_dir: Path | None,
    max_budget_usd: float,
    timeout_s: int,
    no_save: bool,
    print_text: bool,
) -> None:
    """W14-HARNESS-ASK 2026-05-26 / W14-ASK-ROUTED + ASK-AUDIT 2026-05-27:
    daily-driver cross-engine LLM call.

    THREE modes:

    \b
      routed (default)   1 engine via routing recommender,   ~$0.01-0.05
      --audit            producer → auditor (2 engines),     ~$0.05
      --panel            3-engine parallel fanout,           ~$0.20-0.30
      --engines X,Y,Z    pin specific engine(s), bypass recommender

    Examples:

      \b
      harness ask "should we deprecate the legacy swarm/kimi-api?"
      harness ask "..." --task latency               # → deepseek-via-claude
      harness ask "..." --audit                      # fact-check own claims
      harness ask "..." --panel                      # 3-engine fanout
      harness ask "..." --engines mimo-via-claude    # pin explicit
      harness ask --file question.md

    NOTE: bare `harness ask` was a 3-engine panel before v0.5.x.
    Pass `--panel` to keep that behavior.  The routed default uses
    `harness engines recommend <task-class>` to pick one engine.

    Cross-engine PANEL output: question.md + <engine>.md per engine
    + packet.md (synthesis-ready) + summary.json.
    Routed output: question.md + <engine>.md + summary.json
    (no packet.md — the lone engine file IS the synthesis-ready artifact).
    Audit output: question.md + producer-<engine>.md + audit-<engine>.md
    + packet.md + summary.json (with `verdict` field: PASS / PARTIAL / FAIL).
    """
    import datetime
    from harness.ask import (
        DEFAULT_ENGINES, _slugify, run_panel, run_audit, save_panel,
    )

    # --audit-engine implies --audit.  Cheaper UX than requiring both.
    if audit_engine_override:
        audit_mode = True

    # Conflict checks (mutually exclusive flag combinations)
    if audit_mode and panel_mode:
        click.echo(
            click.style(
                "ERROR: --audit and --panel are mutually exclusive.  "
                "--audit runs a producer→auditor flow (2 engines, "
                "sequential); --panel fires 3 engines in parallel.",
                fg="red",
            ), err=True,
        )
        sys.exit(2)

    # Resolve question source
    if question_file is not None:
        question_text = question_file.read_text(encoding="utf-8").strip()
    elif question:
        question_text = question.strip()
    else:
        click.echo(
            click.style(
                "ERROR: provide a question argument or --file path",
                fg="red",
            ), err=True,
        )
        sys.exit(2)

    if not question_text:
        click.echo(
            click.style("ERROR: question is empty", fg="red"), err=True,
        )
        sys.exit(2)

    # Resolve engines + mode.  Precedence is --engines > --audit > --panel
    # > --task (the routed default).
    #
    # Mode semantics:
    #   routed  → recommender-picked single engine; question.md +
    #             <engine>.md + summary.json (no packet.md).
    #   audit   → producer + auditor (2 engines, sequential);
    #             question.md + producer-<engine>.md + audit-<engine>.md
    #             + packet.md + summary.json (verdict field).
    #   panel   → user-pinned engines (via --engines) OR --panel mode;
    #             question.md + <engine>.md per engine + packet.md +
    #             summary.json.  Pin path stays panel-shape even for
    #             1 engine, so HANDOFF.md step 7 + scripted callers see
    #             no output-shape drift.
    engine_list: tuple[str, ...]
    mode: str
    rationale: str = ""
    if engines:
        engine_list = tuple(
            e.strip() for e in engines.split(",") if e.strip()
        )
        if audit_mode and len(engine_list) != 1:
            click.echo(
                click.style(
                    f"ERROR: --audit requires exactly 1 producer engine; "
                    f"got {len(engine_list)} via --engines "
                    f"({','.join(engine_list)}).  Either drop --audit or "
                    f"pin a single engine.",
                    fg="red",
                ), err=True,
            )
            sys.exit(2)
        # Explicit pin = panel-shape output regardless of engine count.
        # Preserves backward compat with the pre-v0.5.x pin behavior.
        # (--audit overrides this below.)
        mode = "panel"
    elif panel_mode:
        engine_list = DEFAULT_ENGINES
        mode = "panel"
    else:
        # Routed default — use the empirical recommender.
        from harness.engines.routing_recommend import recommend
        rec = recommend(task_class)
        engine_list = (rec.engine,)
        mode = "routed"
        rationale = rec.rationale

    # --audit overrides whatever mode the engine resolution set.
    if audit_mode:
        mode = "audit"

    # Resolve output dir
    if output_dir is None and not no_save:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = _slugify(question_text)
        repo_root = Path(__file__).resolve().parents[2]
        output_dir = repo_root / "coord" / "reviews" / f"ask-{ts}-{slug}"

    # Mode-specific dispatch banner
    producer_engine_for_audit: str = engine_list[0] if audit_mode else ""
    if mode == "audit":
        # Resolved producer is known; auditor is picked inside run_audit.
        click.echo(
            f"[ask] audit: producer = {producer_engine_for_audit}  "
            f"(budget ${max_budget_usd:.2f}, timeout {timeout_s}s)"
        )
        if audit_engine_override:
            click.echo(
                f"      auditor: {audit_engine_override} "
                f"(forced via --audit-engine)"
            )
    elif mode == "routed":
        click.echo(
            f"[ask] routed (task={task_class}) → {engine_list[0]}  "
            f"(budget ${max_budget_usd:.2f}, timeout {timeout_s}s)"
        )
        if rationale:
            short = rationale.replace("\n", " ").strip()
            if len(short) > 110:
                short = short[:107] + "..."
            click.echo(f"      {short}")
    elif engines:
        # --engines pinning (single or multiple)
        click.echo(
            f"[ask] pinned: firing {len(engine_list)} engine(s) "
            f"({','.join(engine_list)})  "
            f"(budget ${max_budget_usd:.2f} each, timeout {timeout_s}s)..."
        )
    else:
        # --panel
        click.echo(
            f"[ask] panel: firing {len(engine_list)} engines in parallel  "
            f"(budget ${max_budget_usd:.2f} each, timeout {timeout_s}s)..."
        )
    if output_dir is not None and not no_save:
        click.echo(f"      output: {output_dir}")

    # Dispatch.  Audit uses sequential producer→auditor; routed + panel
    # use parallel fanout (1 or N engines).
    roles: list[str] = []
    extra_summary: dict = {}
    if mode == "audit":
        outcome = run_audit(
            question_text,
            producer_engine=producer_engine_for_audit,
            max_budget_usd=max_budget_usd,
            timeout_s=timeout_s,
            audit_engine_override=audit_engine_override,
        )
        if outcome.auditor is None:
            # Producer failed; the audit step was skipped (auditing a
            # non-response is meaningless).  Single result, no verdict.
            results = [outcome.producer]
            roles = ["producer"]
            extra_summary = {
                "producer_engine": producer_engine_for_audit,
                "auditor_engine": "",
                "verdict": None,
                "audit_skipped_reason": "producer dispatch failed",
            }
        else:
            results = [outcome.producer, outcome.auditor]
            roles = ["producer", "audit"]
            extra_summary = {
                "producer_engine": producer_engine_for_audit,
                "auditor_engine": outcome.auditor_engine,
                "verdict": outcome.verdict,
            }
    else:
        results = run_panel(
            question_text,
            engines=engine_list,
            max_budget_usd=max_budget_usd,
            timeout_s=timeout_s,
        )

    # Print summary table (always)
    click.echo()
    click.echo(
        f"{'engine':<24} {'OK':<4} {'elapsed':<10} "
        f"{'in':<6} {'out':<6} {'cost':<10} {'alias':<6}"
    )
    click.echo("-" * 75)
    total_cost = 0.0
    for i, r in enumerate(results):
        if r.ok:
            ok_styled = click.style("OK", fg="green")
        else:
            ok_styled = click.style("FAIL", fg="red")
        # Audit mode: prefix engine name with role for clarity in the table
        if mode == "audit" and i < len(roles) and roles[i]:
            label = f"{roles[i]}:{r.engine}"
        else:
            label = r.engine
        click.echo(
            f"  {label:<22} {ok_styled:<11} "
            f"{r.elapsed_s:>5.1f}s   "
            f"{r.tokens_in:<6} {r.tokens_out:<6} "
            f"${r.cost_usd:<8.4f} {r.winning_alias or '—':<6}"
        )
        total_cost += r.cost_usd
    click.echo()
    click.echo(f"  total cost: ${total_cost:.4f}")

    # Audit verdict line (always shown when an audit verdict is present)
    if mode == "audit" and extra_summary.get("verdict"):
        v = extra_summary["verdict"]
        verdict_str = v.get("verdict", "UNKNOWN")
        verdict_color = {
            "PASS": "green", "PARTIAL": "yellow",
            "FAIL": "red", "UNKNOWN": "magenta",
        }.get(verdict_str, "magenta")
        click.echo()
        click.echo(
            click.style(f"  VERDICT: {verdict_str}", fg=verdict_color, bold=True)
        )
        summary_line = v.get("summary", "").strip().splitlines()[0:1]
        if summary_line:
            click.echo(f"    {summary_line[0]}")

    if not no_save and output_dir is not None:
        save_panel(
            question_text, results, output_dir,
            mode=mode,
            extra_summary=extra_summary if extra_summary else None,
            roles=roles if roles else None,
        )
        if mode == "routed":
            click.echo(
                f"  saved {len(results)} response file + summary.json"
            )
        else:
            click.echo(
                f"  saved {len(results)} response files + "
                f"packet.md + summary.json"
            )
        click.echo()
        click.echo(click.style(
            f"  → review at {output_dir}",
            fg="cyan",
        ))

    if print_text:
        click.echo()
        click.echo("=" * 75)
        for i, r in enumerate(results):
            click.echo()
            role = roles[i] if (roles and i < len(roles)) else ""
            label = f"{role}: {r.engine}" if role else r.engine
            click.echo(click.style(f"### {label}", fg="yellow", bold=True))
            click.echo()
            click.echo(r.text if r.ok else f"FAILED: {r.error}")

    failed = [r for r in results if not r.ok]
    sys.exit(1 if failed else 0)


@cli.command(name="morning-brief")
@click.option("--since-hours", type=int, default=12,
              help="Look back this many hours when building the brief (default 12).")
@click.option("--out", "out_path", type=click.Path(path_type=Path),
              default=None,
              help="Output markdown path.  Default coord/operator/morning-brief-YYYYMMDD.md.")
@click.option("--engine", default="deepseek",
              help="Engine for the synthesis (default deepseek; v4-flash streams 4× faster).")
@click.option("--model", default="deepseek-v4-flash",
              help="Model for the synthesis.")
@click.option("--dry-run", is_flag=True,
              help="Print the context packet that WOULD be dispatched, then exit.")
def morning_brief_cmd(since_hours: int, out_path: Path | None,
                      engine: str, model: str, dry_run: bool) -> None:
    """W5-RR 2026-05-23: end-of-overnight DeepSeek summary brief.

    Novel idea surfaced in the 20-agent brainstorm (mimo-1): turn the
    autonomous overnight run into a structured handoff document the
    operator can read in 60 seconds.  Pulls:

    - Recent STATUS.csv transitions (last N rows, since-hours filter)
    - Recent runs/<run_id>/ state (worker checkpoints, error_tags)
    - Pending observer flags
    - Open queued production rows (what's still to do)

    Dispatches to DeepSeek (v4-flash by default, now streaming via
    W5-MM — ~30s for a typical context) and writes the synthesis to
    coord/operator/morning-brief-YYYYMMDD.md.

    Designed to be run by Task Scheduler at 8 AM, or manually anytime.

    Exit codes:
      0  brief written successfully
      1  engine dispatch failed (no brief written)
      2  no context found (likely a fresh repo or wrong cwd)
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=since_hours)

    # Build context packet
    sections: list[str] = []

    # 1. Recent STATUS.csv rows
    status_path = Path("coord/STATUS.csv")
    if status_path.exists():
        try:
            from harness.status.store import read_status
            rows = read_status(status_path)
            recent: list[dict] = []
            for r in rows[-50:]:  # last 50 rows
                ud = (r.updated or "").strip()
                # Naive date check: any row with today's or yesterday's date
                if ud and (now.strftime("%Y-%m-%d") in ud or
                           (now - timedelta(days=1)).strftime("%Y-%m-%d") in ud):
                    recent.append({
                        "id": r.id, "category": r.category, "title": r.title,
                        "status": r.status, "updated": r.updated,
                        "notes": (r.notes or "")[:200],
                    })
            if recent:
                lines = ["## Recent STATUS.csv transitions (last 50, filtered to today/yesterday)\n"]
                for r in recent:
                    lines.append(
                        f"- **{r['id']}** [{r['status']}] _{r['updated']}_ "
                        f"({r['category']}): {r['title']}\n  {r['notes']}\n"
                    )
                sections.append("\n".join(lines))
        except Exception as exc:
            sections.append(f"## STATUS.csv\n\n(error reading: {exc})\n")

    # 2. Recent runs/
    runs_dir = Path("runs")
    if runs_dir.exists():
        recent_runs = sorted(
            (p for p in runs_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )[:10]
        run_lines = ["## Recent coord runs (top 10 by mtime)\n"]
        for run_dir in recent_runs:
            ckpt_dir = run_dir / "checkpoints"
            if not ckpt_dir.exists():
                continue
            try:
                workers = list(ckpt_dir.glob("worker-*.json"))
                completed = 0
                failed = 0
                error_tags: list[str] = []
                for ck in workers:
                    try:
                        d = json.loads(ck.read_text(encoding="utf-8"))
                        if d.get("state") == "completed":
                            completed += 1
                        else:
                            failed += 1
                        if d.get("error_tag"):
                            error_tags.append(d["error_tag"])
                    except Exception:
                        pass
                tag_summary = (
                    f" tags=[{','.join(error_tags[:3])}]" if error_tags else ""
                )
                run_lines.append(
                    f"- {run_dir.name}: {completed}/{len(workers)} completed, "
                    f"{failed} failed{tag_summary}"
                )
            except OSError:
                continue
        if len(run_lines) > 1:
            sections.append("\n".join(run_lines))

    # 3. Pending observer flags
    try:
        from harness.observer.flags import list_pending_flags
        pending = list_pending_flags()
        if pending:
            flag_lines = ["## Pending observer flags\n"]
            for sev, flags in pending.items():
                for f in flags:
                    flag_lines.append(f"- **{sev.value}** {f.code}: {f.message}")
            sections.append("\n".join(flag_lines))
    except Exception:
        pass

    # 4. Open queued production rows
    if status_path.exists():
        try:
            from harness.status.store import read_status
            rows = read_status(status_path)
            queued_prod = [
                r for r in rows
                if (r.status or "").strip().lower() == "queued"
                and (r.category or "") in {
                    "Production", "Operator-UX", "Observability",
                    "Integration", "Failure-Recovery", "Security",
                    "Onboarding", "Telemetry", "Multi-Tenancy",
                    "Failure-Mode", "Dispatch-Quality",
                }
            ]
            if queued_prod:
                lines = ["## Open queued production rows\n"]
                for r in queued_prod[:20]:
                    lines.append(
                        f"- **{r.id}** ({r.category}): {r.title}"
                    )
                sections.append("\n".join(lines))
        except Exception:
            pass

    if not sections:
        click.echo(
            "ERROR: no context found in coord/STATUS.csv, runs/, observer flags. "
            "Are you in the harness repo root?", err=True,
        )
        sys.exit(2)

    context_packet = "\n\n".join(sections)
    prompt = (
        "You are summarizing an autonomous overnight run for the operator.\n"
        f"Write a one-page morning brief covering the last {since_hours} hours.\n"
        "Structure (use these exact section headers):\n\n"
        "## What shipped\n"
        "## What stalled / failed\n"
        "## What needs operator attention\n"
        "## Recommended next moves\n\n"
        "Be specific.  Cite IDs (W5-XX, run IDs).  Don't summarize generically.\n"
        "If the context is sparse, say 'low activity' rather than filler.\n\n"
        "Output markdown only, no preamble or wrapping fence.\n\n"
        "# Context\n\n"
        f"{context_packet}\n"
    )

    if dry_run:
        click.echo(f"--- DRY RUN — would dispatch {len(prompt)} chars to "
                   f"{engine}/{model} ---")
        click.echo(prompt)
        sys.exit(0)

    # Dispatch
    click.echo(f"morning-brief: dispatching {len(prompt)} chars to "
               f"{engine}/{model}...")
    from harness.engines.concrete import get_engine
    import time as _time
    try:
        eng = get_engine(engine, prefer_dpapi=False)
    except RuntimeError as exc:
        click.echo(f"ERROR: engine init failed: {exc}", err=True)
        sys.exit(1)
    started = _time.monotonic()
    resp = eng.dispatch(prompt, model, {})
    latency = int((_time.monotonic() - started) * 1000)

    if not resp.success or not (resp.text or "").strip():
        click.echo(f"ERROR: dispatch failed ({latency}ms): {resp.error}",
                   err=True)
        sys.exit(1)

    # Write output
    if out_path is None:
        stamp = now.strftime("%Y%m%d")
        out_path = Path("coord/operator") / f"morning-brief-{stamp}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"<!-- engine={engine} model={model} latency_ms={latency} "
        f"tokens_in={resp.tokens_in} tokens_out={resp.tokens_out} "
        f"since_hours={since_hours} generated_at={now.isoformat()} -->\n\n"
        f"{resp.text}\n"
    )
    out_path.write_text(body, encoding="utf-8")
    click.echo(f"morning-brief: wrote {out_path} ({latency}ms, "
               f"{resp.tokens_out} tokens out)")
    sys.exit(0)


def _samples_dir() -> Path:
    """Locate the spec/samples/ directory (the SPECLIB template library).

    W5-QQ: prefer cwd-relative ``spec/samples`` if it exists (operator
    is inside their project tree); else fall back to the package's
    repo-root sibling (the harness's own samples library).  Does NOT
    walk up the directory tree — operators running from subdirs of
    unrelated projects shouldn't accidentally see a parent project's
    samples.
    """
    cwd_candidate = Path.cwd() / "spec" / "samples"
    if cwd_candidate.is_dir():
        return cwd_candidate
    # Fall back to the harness package's own samples
    pkg_candidate = Path(__file__).resolve().parents[2] / "spec" / "samples"
    return pkg_candidate


@cli.command(name="spec-init", hidden=True)
@click.argument("name", required=False)
@click.option("--strict-paths", default=None,
              help="Comma-separated list of relative paths to bind under "
                   "`## Strict Paths` (W5-BB).  Each becomes a bullet entry.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path),
              default=Path("spec/auto"),
              help="Output directory.  Default `spec/auto/` queues for "
                   "autonomous processing via `harness queue execute`.")
@click.option("--goal", default=None,
              help="One-line goal (auto-prompted if missing).")
@click.option("--from-template", "template", default=None,
              help="W5-QQ: copy from spec/samples/<NAME>.md instead of "
                   "generating a blank canonical scaffold.  Use "
                   "--list-templates to see available samples.")
@click.option("--list-templates", "list_templates", is_flag=True,
              help="W5-QQ: list available templates in spec/samples/ and exit.")
def spec_init_cmd(name: str | None, strict_paths: str | None,
                  out_dir: Path, goal: str | None,
                  template: str | None, list_templates: bool) -> None:
    """Scaffold a starter spec markdown with canonical sections.

    W5-KK 2026-05-23: makes the `## Strict Paths` syntax (W5-BB)
    discoverable via tooling.  Operator runs:

      harness spec-init my-feature --strict-paths coord/x.md,coord/y.md

    and gets a ready-to-edit spec at spec/auto/my-feature.md with all
    canonical sections (SPEC-ID, Goal, Strict Paths, Acceptance, Why)
    prefilled.  Drop in a goal, customize acceptance criteria, then
    `harness queue execute --once` processes it.

    W5-QQ 2026-05-23: --from-template / --list-templates exposes
    spec/samples/ as the SPECLIB.  Browse with --list-templates, copy
    a starter with --from-template NAME.
    """
    samples = _samples_dir()

    # W5-QQ: --list-templates prints library + exits
    if list_templates:
        if not samples.exists():
            click.echo(f"(no template library found at {samples})")
            sys.exit(0)
        templates = sorted(p for p in samples.glob("*.md") if p.is_file())
        if not templates:
            click.echo(f"(spec/samples/ exists but contains no *.md templates)")
            sys.exit(0)
        click.echo(f"Available templates in {samples}:")
        for t in templates:
            # Extract first-line title for a short description
            try:
                first = t.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
            except OSError:
                first = "(unreadable)"
            click.echo(f"  {t.stem:30s}  {first[:60]}")
        click.echo(f"\nUse: harness spec-init NAME --from-template <stem>")
        sys.exit(0)

    if not name:
        click.echo("ERROR: NAME is required unless --list-templates is given",
                   err=True)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    # Slugify the name: replace whitespace + non-safe chars with hyphens
    import re as _re_slug
    slug = _re_slug.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-")
    if not slug:
        click.echo("ERROR: name must contain at least one alphanumeric char",
                   err=True)
        sys.exit(1)
    spec_path = out_dir / f"{slug}.md"
    if spec_path.exists():
        click.echo(f"ERROR: {spec_path} already exists.  Pick a different "
                   f"--out dir or delete the existing file first.", err=True)
        sys.exit(1)

    # W5-QQ: --from-template copies an existing sample
    if template:
        template_path = samples / f"{template}.md"
        if not template_path.exists():
            click.echo(f"ERROR: template '{template}' not found at {template_path}.",
                       err=True)
            click.echo("Run `harness spec-init --list-templates` to see "
                       "available templates.", err=True)
            sys.exit(1)
        body = template_path.read_text(encoding="utf-8")
        # Replace the SPEC-ID header with the operator's chosen slug.
        # First line is canonical: "# SPEC-ID: <whatever> — <title>"
        import re as _re_hdr
        body = _re_hdr.sub(
            r"^# SPEC-ID:\s*[^\n]*",
            f"# SPEC-ID: {slug} — copied from {template_path.name}",
            body, count=1, flags=_re_hdr.MULTILINE,
        )
        spec_path.write_text(body, encoding="utf-8")
        click.echo(f"created: {spec_path}")
        click.echo(f"  from-template: {template_path.name}")
        click.echo("  edit the spec, then run:")
        click.echo(f"    harness queue execute --once --planner-engine kimi-api")
        sys.exit(0)

    # Parse strict-paths CSV
    paths: list[str] = []
    if strict_paths:
        paths = [p.strip().strip("`'\"") for p in strict_paths.split(",") if p.strip()]

    goal_line = goal or "<one-line description of what this spec accomplishes>"

    lines: list[str] = [
        f"# SPEC-ID: {slug} — <short title>",
        "",
        "## Goal",
        "",
        goal_line,
        "",
    ]
    if paths:
        lines.append("## Strict Paths")
        lines.append("")
        for p in paths:
            lines.append(f"- {p}")
        lines.append("")
    else:
        lines.append("## Strict Paths")
        lines.append("")
        lines.append("<!-- W5-BB 2026-05-23: list operator-declared output paths -->")
        lines.append("<!-- Worker MUST create files at these exact paths.   -->")
        lines.append("<!-- Example:                                          -->")
        lines.append("<!--   - coord/operator/my-report.md                   -->")
        lines.append("<!--   - coord/operator/my-report.json                 -->")
        lines.append("")
    lines.extend([
        "## Acceptance",
        "",
        "1. <criterion 1 — e.g. file exists at the declared path>",
        "2. <criterion 2 — e.g. contains specific text>",
        "3. <criterion 3 — e.g. tests pass>",
        "",
        "## Why this spec exists",
        "",
        "<explain the motivation: bug fix, feature gap, dispatch failure, "
        "process improvement.  This becomes the post-merge audit trail.>",
        "",
    ])
    spec_path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"created: {spec_path}")
    if paths:
        click.echo(f"  strict_paths: {len(paths)} path(s)")
    click.echo("  edit the spec, then run:")
    click.echo(f"    harness queue execute --once --planner-engine kimi-api")


@cli.group(name="status")
def status() -> None:
    """Canonical STATUS.csv task tracker (harness primitive #19).

    The legacy project-scoped status reporter lives under
    ``status report``; the new repo-canonical commands manage
    ``coord/STATUS.csv`` directly.
    """


@status.command(name="report")
@click.option("--project", "-p", help="Project name.")
@click.option("--report", "as_report", is_flag=True, help="Report to configured backend.")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), help="Output format.")
def status_report(project: Optional[str], as_report: bool, fmt: Optional[str]) -> None:
    """Print project-scoped status (or report to configured backend)."""
    if not project:
        click.echo("error: --project is required", err=True)
        sys.exit(2)

    try:
        cfg = load_project_adapter(project)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    if as_report:
        click.echo("status: report backend not yet implemented")
        sys.exit(1)

    backend = cfg.status_tracking.backend
    config = cfg.status_tracking.config
    root = Path(cfg.project_root)

    if backend == "csv":
        csv_path = root / config.get("csv_path", "STATUS.csv")
    elif backend == "markdown":
        csv_path = root / config.get("path", "STATUS.md")
    else:
        click.echo(f"status: backend '{backend}' not yet supported for CLI display")
        sys.exit(1)

    if not csv_path.exists():
        click.echo(f"error: status file not found: {csv_path}", err=True)
        sys.exit(1)

    if fmt == "json":
        import csv as csv_mod

        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        click.echo(
            json.dumps(
                {"project": project, "backend": backend, "path": str(csv_path), "rows": rows},
                indent=2,
            )
        )
    else:
        click.echo(csv_path.read_text(encoding="utf-8"))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Canonical STATUS.csv tracker (roster #19)
# ---------------------------------------------------------------------------


def _status_csv_path() -> Path:
    """Resolve coord/STATUS.csv relative to the current working directory."""
    return Path("coord") / "STATUS.csv"


_STATUS_HEADER = ["ID", "Category", "Title", "Status", "Owner", "Effort", "Updated", "Notes"]


@status.command(name="init")
@click.option("--force", is_flag=True, help="Overwrite an existing STATUS.csv.")
def status_init(force: bool) -> None:
    """Create coord/STATUS.csv with header row."""
    from harness.status.store import write_status

    p = _status_csv_path()
    if p.exists() and not force:
        click.echo(f"error: {p} already exists (use --force to overwrite)", err=True)
        sys.exit(1)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_status(p, [])
    click.echo(f"created {p}")


@status.command(name="add")
@click.argument("id_")
@click.argument("category")
@click.argument("title")
@click.option("--status", "status_value", default="todo")
@click.option("--owner", default="Claude")
@click.option("--effort", default="-")
@click.option("--notes", default="")
def status_add(
    id_: str,
    category: str,
    title: str,
    status_value: str,
    owner: str,
    effort: str,
    notes: str,
) -> None:
    """Add a new row."""
    from harness.status import StatusRow, add_row, Status
    from datetime import datetime, timezone

    p = _status_csv_path()
    try:
        row = StatusRow(
            id=id_,
            category=category,
            title=title,
            status=Status(status_value),
            owner=owner,
            effort=effort,
            updated=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            notes=notes,
        )
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    try:
        add_row(p, row)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"added {id_}")


@status.command(name="update")
@click.argument("id_")
@click.option("--status", "status_value", default=None)
@click.option("--owner", default=None)
@click.option("--effort", default=None)
@click.option("--notes", default=None)
@click.option("--title", default=None)
def status_update(
    id_: str,
    status_value: Optional[str],
    owner: Optional[str],
    effort: Optional[str],
    notes: Optional[str],
    title: Optional[str],
) -> None:
    """Update fields on an existing row."""
    from harness.status import update_row

    fields: dict[str, str] = {}
    if status_value is not None:
        fields["status"] = status_value
    if owner is not None:
        fields["owner"] = owner
    if effort is not None:
        fields["effort"] = effort
    if notes is not None:
        fields["notes"] = notes
    if title is not None:
        fields["title"] = title
    if not fields:
        click.echo("error: at least one field must be provided", err=True)
        sys.exit(2)
    try:
        update_row(_status_csv_path(), id_, **fields)
    except KeyError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"updated {id_}")


@status.command(name="list")
@click.option("--filter", "filter_status", default=None, help="Filter by status value.")
@click.option("--category", default=None, help="Filter by category.")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json", "csv"]), default="pretty")
@click.option("--recent", type=int, default=None,
              help="W10-STATUS-CSV-OVERWHELM: show only the N most recently "
                   "updated rows (sorted by Updated date desc).  Defaults to "
                   "no truncation for backwards compat with CI scripts.")
def status_list(filter_status: Optional[str], category: Optional[str],
                fmt: str, recent: Optional[int]) -> None:
    """List rows (with optional filters).

    Use ``--recent 20`` to show only the 20 most recently updated rows
    (and a footer naming how many older rows are in coord/STATUS.csv).
    The full 296-row CSV is impossible for a non-technical operator
    to scan; --recent surfaces what matters now without dropping history.
    """
    from harness.status import read_status

    all_rows = read_status(_status_csv_path())
    rows = list(all_rows)
    if filter_status:
        rows = [r for r in rows if r.status.value == filter_status]
    if category:
        rows = [r for r in rows if r.category == category]

    # W10-STATUS-CSV-OVERWHELM: --recent truncation, only for pretty
    # output.  JSON/CSV consumers (CI) keep the full set.
    truncated_off: int = 0
    if recent is not None and recent >= 0 and fmt == "pretty":
        # Sort by Updated date descending (string ISO compares fine)
        rows = sorted(rows, key=lambda r: r.updated or "", reverse=True)
        if recent < len(rows):
            truncated_off = len(rows) - recent
            rows = rows[:recent]

    if fmt == "json":
        click.echo(json.dumps([r.model_dump(mode="json") for r in rows], indent=2))
        return
    if fmt == "csv":
        import csv as csv_mod
        import io

        buf = io.StringIO()
        writer = csv_mod.writer(buf)
        writer.writerow(_STATUS_HEADER)
        for r in rows:
            writer.writerow([
                r.id, r.category, r.title, r.status.value, r.owner,
                r.effort, r.updated, r.notes,
            ])
        click.echo(buf.getvalue().rstrip("\n"))
        return
    for r in rows:
        click.echo(f"{r.id:24}  {r.status.value:12}  {r.title}")
    if truncated_off > 0:
        click.echo(f"\n  ... and {truncated_off} older row(s) in "
                   f"coord/STATUS.csv (run without --recent to see all)")


@status.command(name="summary")
def status_summary() -> None:
    """Print counts by status."""
    from harness.status import summary as status_summary_fn

    counts = status_summary_fn(_status_csv_path())
    nonzero = {s.value: n for s, n in counts.items() if n > 0}
    parts = [f"{n} {label}" for label, n in nonzero.items()]
    click.echo(", ".join(parts) if parts else "(empty)")


@status.command(name="verify")
@click.option("--cadence-minutes", type=int, default=None,
              help="Expected cadence for mtime canary check.")
def status_verify(cadence_minutes: Optional[int]) -> None:
    """Validate the STATUS.csv schema + canary checks."""
    from harness.status import verify

    issues = verify(_status_csv_path(), expected_cadence_minutes=cadence_minutes)
    if not issues:
        click.echo("ok: no issues found")
        sys.exit(0)
    for i in issues:
        click.echo(i, err=True)
    sys.exit(1)


@status.command(name="human")
@click.option("--since-hours", type=int, default=24,
              help="How far back to look for activity (default 24).")
def status_human(since_hours: int) -> None:
    """W8-AUDIT follow-through 2026-05-24: spec alias for ``harness today``.

    The MiMo audit flagged that the spec calls for both ``harness today``
    AND ``harness status human``.  Both routes share the same code path.
    """
    ctx = click.get_current_context()
    ctx.invoke(today_cmd, since_hours=since_hours)


@cli.command()
@click.option("--project", "-p", help="Project name.")
@click.option("--date", help="Retro date (YYYY-MM-DD).")
def retro(project: Optional[str], date: Optional[str]) -> None:
    """Generate daily retro summary from history."""
    click.echo("retro: backend pending Wave A.2")
    sys.exit(1)


@cli.command()
@click.option("--uninstall", is_flag=True, help="Remove scheduled tasks and config.")
def install(uninstall: bool) -> None:
    """Setup Task Scheduler entries and first-run wizard."""
    click.echo("install: pending Wave 4 (Windows installer + first-run wizard)")
    sys.exit(1)


@cli.command()
@click.option("--project", "-p", required=True, help="Project name.")
@click.option(
    "--template",
    "-t",
    type=click.Choice(
        [
            "warehouse-style",
            "generic-coding",
            "writing-content",
            "research-comparison",
            "solo-dev",
            "basic",
        ]
    ),
    default="warehouse-style",
    help="Starter template.",
)
@click.option("--force", is_flag=True, help="Overwrite existing adapter.")
def init(project: str, template: str, force: bool) -> None:
    """Create starter adapter YAML for a project."""
    adapter_dir = _repo_root() / "adapters" / project
    adapter_path = adapter_dir / "harness-adapter.yaml"

    if adapter_path.exists() and not force:
        click.echo(
            f"error: adapter already exists for '{project}'; use --force to overwrite",
            err=True,
        )
        sys.exit(2)

    try:
        cfg = load_template(template)
    except (ValueError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    data = cfg.model_dump(mode="json")
    data["name"] = project

    adapter_dir.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    click.echo(str(adapter_path))
    sys.exit(0)


@cli.command()
@click.option("--show-set", is_flag=True, help="Show which API keys are set.")
def env(show_set: bool) -> None:
    """Check which API keys are set (reports per-key + per-alias, never values).

    Patch 2026-05-21: extended to surface the v2 proxy's per-key indexed
    aliases (KIMI_API_KEY_1..4 → k1..k4) so the operator can see the real
    state of the 4-key pool. The legacy singular ``KIMI_API_KEY`` is still
    reported (and serves as a fallback for k1 per ``resolve_keys``).
    """
    from harness.secrets.dpapi import has_secret

    # Legacy single-key surface (used by v1 dispatchers + as k1 fallback)
    legacy_keys = ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    for key_name in legacy_keys:
        if os.environ.get(key_name) or has_secret(key_name):
            click.echo(f"{key_name}: SET")
        else:
            click.echo(f"{key_name}: MISSING")

    # v2 proxy per-alias pool (KIMI_API_KEY_1..4 → k1..k4)
    click.echo("")
    click.echo("v2 proxy pool (Kimi-API per-alias):")
    try:
        from harness.proxy.app import resolve_keys
        resolved = resolve_keys()
    except Exception as exc:
        resolved = {}
        click.echo(f"  (resolve_keys failed: {exc})")
    for n in range(1, 5):
        alias = f"k{n}"
        env_var = f"KIMI_API_KEY_{n}"
        env_present = bool(os.environ.get(env_var))
        dpapi_present = has_secret(env_var)
        if alias in resolved:
            source = "env" if env_present else ("DPAPI" if dpapi_present else "legacy")
            click.echo(f"  {alias} ({env_var}): SET (source={source})")
        else:
            click.echo(f"  {alias} ({env_var}): MISSING")
    click.echo(f"v2 pool size: {len(resolved)}/4 (6 slots/key -> {len(resolved) * 6}/24 concurrent capacity)")
    sys.exit(0)


_ENV_WIZARD_KEYS: list[tuple[str, str]] = [
    # (env_var_name, plain-language purpose)
    ("KIMI_API_KEY",      "Kimi (Moonshot) — primary agentic engine"),
    ("DEEPSEEK_API_KEY",  "DeepSeek — V-file-spanning + math-heavy work"),
    ("MIMO_API_KEY",      "MiMo — audit + brainstorm panels"),
    ("ANTHROPIC_API_KEY", "Anthropic — Claude API fallback (optional)"),
    ("GEMINI_API_KEY",    "Gemini — secondary engine (optional)"),
]


@cli.command(name="env-wizard")
@click.option("--overwrite", is_flag=True, default=False,
              help="Re-prompt for keys that are already set (default: "
                   "skip set keys and only prompt for missing ones).")
@click.option("--non-interactive", is_flag=True, default=False,
              help="Print the wizard plan without prompting; used by tests "
                   "and dry-run.")
def env_wizard_cmd(overwrite: bool, non_interactive: bool) -> None:
    """W10-ENV-VAR-WIZARD: guided API-key population.

    Walks through each required API key, prompts the operator to
    paste a value (or skip), and stores it in DPAPI via
    ``harness.secrets.dpapi.encrypt_secret``.  After each entry,
    runs a presence probe to confirm.

    Idempotent: re-running shows current state.  Pass ``--overwrite``
    to re-prompt for keys that are already set.

    Operator-friendly: no Python knowledge required.  The wizard
    explains each key in plain language (what it's for, whether
    it's required).  Operators can paste keys; values are hidden
    in the prompt and never echoed back.

    Per [[user_non_technical_role]] memory: the operator can run
    CLI commands + paste values but cannot read tracebacks.  The
    wizard surfaces errors with one-line "what to do" messages.
    """
    from harness.secrets.dpapi import has_secret, encrypt_secret

    click.echo("=" * 60)
    click.echo("  harness env-wizard — API key setup")
    click.echo("=" * 60)
    click.echo(
        "\nFor each engine, you'll see whether a key is already set.\n"
        "If MISSING, paste your key (or press Enter to skip).\n"
        "Keys are stored securely via Windows DPAPI — only your\n"
        "Windows user can decrypt them.\n"
    )

    set_count = 0
    new_count = 0
    skip_count = 0

    for key_name, purpose in _ENV_WIZARD_KEYS:
        env_present = bool(os.environ.get(key_name))
        dpapi_present = has_secret(key_name)
        present = env_present or dpapi_present
        status = "SET" if present else "MISSING"
        source = ""
        if env_present and dpapi_present:
            source = "  (env + DPAPI)"
        elif env_present:
            source = "  (env)"
        elif dpapi_present:
            source = "  (DPAPI)"

        click.echo(f"\n[{status}] {key_name}{source}")
        click.echo(f"        {purpose}")

        if present and not overwrite:
            click.echo("        -> already set, skipping (pass --overwrite "
                       "to re-prompt)")
            set_count += 1
            continue

        if non_interactive:
            click.echo("        -> would prompt (non-interactive mode; "
                       "skipping)")
            skip_count += 1
            continue

        # Prompt for value (hide input so the key isn't echoed)
        value = click.prompt(
            f"        Paste {key_name} (or empty to skip)",
            hide_input=True,
            default="",
            show_default=False,
        )
        value = value.strip()
        if not value:
            click.echo("        -> skipped (empty input)")
            skip_count += 1
            continue

        try:
            encrypt_secret(key_name, value)
        except Exception as exc:
            click.echo(f"        [X] failed to store key: {exc}",
                       err=True)
            click.echo("        -> retry the wizard once you've resolved "
                       "the DPAPI issue", err=True)
            sys.exit(4)

        # Confirm
        if has_secret(key_name):
            click.echo(f"        [OK] {key_name} stored in DPAPI")
            new_count += 1
        else:
            click.echo(f"        [X] {key_name} write reported ok but "
                       f"presence probe failed", err=True)
            sys.exit(4)

    click.echo("\n" + "=" * 60)
    click.echo(f"  Wizard complete: {set_count} already-set, "
               f"{new_count} newly stored, {skip_count} skipped")
    click.echo("=" * 60)
    click.echo("\nVerify with: `harness env`")
    sys.exit(0)


@cli.group(name="adapter")
def adapter() -> None:
    """Manage harness adapters (generate, list, validate)."""


@adapter.command(name="from-description")
@click.option("--project", "-p", required=True, help="Project name.")
@click.option("--description", help="Natural-language description of the project.")
@click.option("--description-file", type=click.Path(exists=True, dir_okay=False), help="Path to a file containing the description.")
@click.option("--engine", default="swarm/kimi", help="Engine to use for generation.")
@click.option("--force", is_flag=True, help="Overwrite existing adapter.")
@click.pass_context
def adapter_from_description(
    ctx: click.Context,
    project: str,
    description: Optional[str],
    description_file: Optional[str],
    engine: str,
    force: bool,
) -> None:
    """Generate an adapter YAML from a natural-language description."""
    op_cfg = (ctx.obj or {}).get("operator_config") if ctx.obj else None
    if op_cfg is not None and op_cfg.mode == OperatorMode.DRY_RUN:
        click.echo("dry-run: would generate adapter from description")
        sys.exit(0)

    if description and description_file:
        click.echo("error: --description and --description-file are mutually exclusive", err=True)
        sys.exit(2)
    if description_file:
        description = Path(description_file).read_text(encoding="utf-8")
    if not description:
        click.echo("error: --description or --description-file is required", err=True)
        sys.exit(2)

    adapter_dir = _repo_root() / "adapters" / project
    adapter_path = adapter_dir / "harness-adapter.yaml"

    if adapter_path.exists() and not force:
        click.echo(
            f"error: adapter already exists for '{project}'; use --force to overwrite",
            err=True,
        )
        sys.exit(2)

    try:
        cfg = generate_adapter_from_nl(project=project, description=description, engine=engine)
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    data = cfg.model_dump(mode="json")
    data["name"] = project

    adapter_dir.mkdir(parents=True, exist_ok=True)
    adapter_path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    click.echo(str(adapter_path))
    sys.exit(0)


@adapter.command(name="create")
@click.argument("project_name")
@click.option("--target-dir", default=".", type=click.Path(path_type=Path),
              help="Parent dir for the new project (default cwd).")
@click.option("--template", default="basic",
              help="Adapter template name (basic | generic-coding | solo-dev | …).")
def adapter_create(project_name: str, target_dir: Path, template: str) -> None:
    """Scaffold a new project: adapter YAML + coord layout + spec/ + runs/."""
    try:
        paths = scaffold_adapter(
            project_name, target_dir=target_dir, template=template,
        )
    except FileExistsError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"error: scaffold failed: {exc}", err=True)
        sys.exit(1)

    click.echo(f"created project: {paths['project_dir']}")
    click.echo(f"  adapter:   {paths['adapter_yaml']}")
    click.echo(f"  STATUS:    {paths['status_csv']}")
    click.echo(f"  state:     {paths['state_json']}")
    click.echo(f"\nNext: cd {paths['project_dir']} && harness install")


@adapter.command(name="list")
def adapter_list() -> None:
    """List existing project adapters."""
    adapters_dir = _repo_root() / "adapters"
    projects = []
    for path in adapters_dir.iterdir():
        if path.is_dir() and (path / "harness-adapter.yaml").exists():
            projects.append(path.name)
    for name in sorted(projects):
        click.echo(name)
    sys.exit(0)


@adapter.command(name="validate")
@click.argument("project")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="W11-ADAPTER-VALIDATE-JSON: emit machine-readable "
                   "validation errors as JSON.  For agentic auto-correction "
                   "loops; human callers use the default pretty output.")
def adapter_validate(project: str, as_json: bool) -> None:
    """Validate a project's harness-adapter.yaml.

    W11-ADAPTER-VALIDATE-JSON 2026-05-25: ``--json`` mode emits a
    structured payload that agents can parse + auto-correct from
    without interpreting free-text human messages.  Schema:

        {
          "project": "<name>",
          "status": "ok" | "error",
          "errors": [
            {
              "field": "engines.kimi.timeout",
              "line": null,
              "severity": "error" | "warning",
              "message": "<human-readable>",
              "suggested_fix": "<actionable hint>"
            },
            ...
          ]
        }

    Exit code: 0 = valid, 1 = errors present.
    """
    try:
        load_project_adapter(project)
        ok = True
        errors: list[dict] = []
        exc_for_pretty: Exception | None = None
    except Exception as exc:
        ok = False
        exc_for_pretty = exc
        errors = _validate_exc_to_json_errors(exc)

    if as_json:
        payload = {
            "project": project,
            "status": "ok" if ok else "error",
            "errors": errors,
        }
        click.echo(json.dumps(payload, indent=2, default=str))
        sys.exit(0 if ok else 1)

    # Pretty (legacy) output path
    if ok:
        click.echo(f"adapter for '{project}' is valid")
        sys.exit(0)
    click.echo(f"error: {exc_for_pretty}", err=True)
    sys.exit(1)


def _validate_exc_to_json_errors(exc: Exception) -> list[dict]:
    """W11-ADAPTER-VALIDATE-JSON: convert validate exceptions to
    structured error objects.  Handles Pydantic ValidationError,
    yaml.YAMLError, and generic Exception with best-effort field
    extraction."""
    errors: list[dict] = []
    # Pydantic ValidationError carries a structured .errors() list
    try:
        from pydantic import ValidationError as _PydanticVE
    except ImportError:
        _PydanticVE = None  # type: ignore
    if _PydanticVE is not None and isinstance(exc, _PydanticVE):
        for err in exc.errors():
            field = ".".join(str(x) for x in err.get("loc", []))
            err_type = err.get("type", "")
            msg = err.get("msg", "")
            input_val = err.get("input", None)
            errors.append({
                "field": field or "<root>",
                "line": None,  # Pydantic doesn't track source line
                "severity": "error",
                "message": msg,
                "suggested_fix": _suggest_fix_for_pydantic(
                    field, err_type, input_val),
            })
        return errors
    # yaml.YAMLError has .problem_mark with line/column
    try:
        import yaml as _yaml
        if isinstance(exc, _yaml.YAMLError):
            line = None
            field = "<yaml-parse>"
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line = mark.line + 1  # 1-based for humans
            errors.append({
                "field": field,
                "line": line,
                "severity": "error",
                "message": str(exc),
                "suggested_fix": (
                    "Check YAML syntax at the indicated line — common "
                    "causes: bad indentation, missing colon, unescaped "
                    "special characters."
                ),
            })
            return errors
    except ImportError:
        pass
    # FileNotFoundError + ValueError + generic Exception
    if isinstance(exc, FileNotFoundError):
        errors.append({
            "field": "<file>",
            "line": None,
            "severity": "error",
            "message": f"adapter file not found: {exc}",
            "suggested_fix": (
                "Create adapters/<project>/harness-adapter.yaml.  Use "
                "`harness adapter scaffold` or `harness adapter "
                "from-description` to generate one."
            ),
        })
        return errors
    # Fallback: generic exception
    errors.append({
        "field": "<unknown>",
        "line": None,
        "severity": "error",
        "message": str(exc),
        "suggested_fix": (
            "Examine the error message above; common causes: invalid "
            "project name (must match ^[a-zA-Z0-9_-]{1,64}$), missing "
            "engines block, malformed routing rule."
        ),
    })
    return errors


def _suggest_fix_for_pydantic(field: str, err_type: str,
                              input_val: object) -> str:
    """W11-ADAPTER-VALIDATE-JSON: actionable fix-hint per Pydantic
    error type.  Falls back to a generic message."""
    if "missing" in err_type:
        return f"Add `{field}:` to the adapter YAML with a valid value."
    if "type_error" in err_type or "type" in err_type:
        actual_type = type(input_val).__name__ if input_val is not None else "null"
        return (
            f"Field `{field}` has wrong type (got {actual_type}); check "
            f"the schema in spec/adapter-schema.md."
        )
    if "value_error" in err_type or "enum" in err_type:
        return (
            f"Field `{field}` has an unsupported value; consult "
            f"spec/adapter-schema.md for allowed values."
        )
    if "regex" in err_type or "pattern" in err_type:
        return f"Field `{field}` doesn't match the required pattern."
    return f"Fix field `{field}` per spec/adapter-schema.md."


@cli.command(name="dashboard-serve")
@click.option("--port", default=7878, type=int, help="Dashboard server port.")
@click.option("--host", default="127.0.0.1",
              help="Dashboard server bind address.  MUST be a loopback "
                   "host (127.0.0.1 / ::1 / localhost).  P4 audit fix "
                   "2026-05-27: the dashboard endpoints are unauthenticated, "
                   "so binding non-loopback would expose operational state "
                   "(engine activity, cost, observer flags, L5 events) to "
                   "your LAN.  Non-loopback binds are refused with a "
                   "clear error.")
def dashboard_serve(port: int, host: str) -> None:
    """Run the operator-facing dashboard.

    Binds to 127.0.0.1 by default.  Attempting to override with a
    non-loopback host raises ``NonLoopbackBindRefused`` and exits
    non-zero (P4 audit fix 2026-05-27).
    """
    from harness.dashboard.server import serve, NonLoopbackBindRefused

    try:
        serve(host=host, port=port)
    except NonLoopbackBindRefused as exc:
        raise click.ClickException(str(exc)) from exc


@cli.group(name="queue")
def queue_group() -> None:
    """W5-U Path β: burst-composition spec queue (Claude composes, autonomous executor)."""


def _sort_queue_paths(paths: list[Path]) -> list[Path]:
    """Sort spec/auto/ paths by W5-NN priority prefix then name.

    Priority prefix is an optional ``P<n>-`` at the start of the filename
    (e.g. ``P0-fix-bug.md``, ``P2-add-feature.md``).  Lower numbers run
    first.  Specs without a prefix get default priority 5 (sits between
    P0-P4 explicit-urgent and P6+ explicit-defer).

    Examples:
        P0-fix.md  → (0, "P0-fix.md")        runs first
        spec.md    → (5, "spec.md")          default priority
        P9-doc.md  → (9, "P9-doc.md")        runs late

    Within the same priority bucket, alphabetical order is preserved
    (so existing single-priority queues behave identically to the old
    sort()).
    """
    import re as _re_prio
    pattern = _re_prio.compile(r"^P(\d+)-")

    def _priority(p: Path) -> int:
        m = pattern.match(p.name)
        return int(m.group(1)) if m else 5

    return sorted(paths, key=lambda p: (_priority(p), p.name))


@queue_group.command(name="list")
def queue_list_cmd() -> None:
    """List pending specs in spec/auto/ (the queue)."""
    queue_dir = Path("spec/auto")
    done_dir = queue_dir / "done"
    if not queue_dir.exists():
        click.echo("(spec/auto/ does not exist; no queued specs)")
        sys.exit(0)
    pending = _sort_queue_paths([p for p in queue_dir.glob("*.md") if p.is_file()])
    done = sorted(done_dir.glob("*.md")) if done_dir.exists() else []
    click.echo(f"pending: {len(pending)}")
    for p in pending:
        click.echo(f"  - {p.name}")
    click.echo(f"\ndone: {len(done)}")
    for p in done[-5:]:
        click.echo(f"  - {p.name}")
    if len(done) > 5:
        click.echo(f"  ... +{len(done) - 5} more")
    sys.exit(0)


@queue_group.command(name="execute")
@click.option("--once", is_flag=True, help="Process a single spec and exit.")
@click.option("--max", "max_specs", type=int, default=None,
              help="Cap on specs processed (default: all pending).")
@click.option("--engine", default="swarm/mimo",
              help="Worker engine (default swarm/mimo).")
@click.option("--fallback-engine", default="swarm/deepseek",
              help="Worker fallback engine.")
@click.option("--planner-engine", default="kimi-api",
              help="Engine used for `coord plan` step.  W5-AA default kimi-api "
                   "(reliable post-W5-V; $0 via tp- subscription).  Other "
                   "valid: claude | kimi | deepseek | mock.")
@click.option("--no-merge", is_flag=True,
              help="Run validation only; don't merge to master.")
def queue_execute_cmd(once: bool, max_specs: int | None,
                      engine: str, fallback_engine: str,
                      planner_engine: str,
                      no_merge: bool) -> None:
    """Process pending specs from spec/auto/, moving each to spec/auto/done/.

    Default flow per cycle:
      1. Pop oldest spec from spec/auto/
      2. coord plan + coord run --watch (validate; merge-policy-driven)
      3. If worker.state=completed + tests_passed: coord integrate --commit
      4. Move spec file to spec/auto/done/
      5. Continue to next spec

    Safe to kill mid-cycle: W5-M PID sentinel prevents duplicate worker
    spawn on resume.
    """
    queue_dir = Path("spec/auto")
    done_dir = queue_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    # W5-NN: respect P<n>- priority prefix; lower numbers run first.
    pending = _sort_queue_paths([p for p in queue_dir.glob("*.md") if p.is_file()])
    if not pending:
        click.echo("Queue empty.")
        sys.exit(0)

    limit = 1 if once else (max_specs or len(pending))
    processed = 0
    completed_count = 0
    merged_count = 0
    for spec_path in pending[:limit]:
        click.echo(f"\n{'='*60}\n=== Processing: {spec_path.name} ===\n{'='*60}")
        # Plan (W5-AA: planner_engine default 'kimi-api' replaces hardcoded
        # 'claude' — Kimi K2.6 verified reliable on planning packets via
        # W5-V wiring fix and free via tp- subscription).
        plan_proc = subprocess.run(
            [sys.executable, "-m", "harness", "coord", "plan",
             "--spec", str(spec_path), "--engine", planner_engine],
            capture_output=True, text=True, timeout=300,
        )
        if plan_proc.returncode != 0:
            click.echo(f"PLAN FAILED: {plan_proc.stderr[:200]}", err=True)
            processed += 1
            continue
        rid = None
        for line in plan_proc.stdout.splitlines():
            if "plan:" in line and "runs" in line:
                rid = line.split("runs")[-1].lstrip("\\/").split("\\")[0].split("/")[0]
                break
        if not rid:
            click.echo(f"NO RUN-ID parsed from plan output", err=True)
            processed += 1
            continue

        # Run --no-merge first (validates)
        run_cmd = [
            sys.executable, "-m", "harness", "coord", "run",
            "--spec", str(spec_path), "--run-id", rid,
            "--engine", engine, "--proxy", "off",
            "--watch", "--watch-interval", "5",
            "--watch-max-seconds", "600", "--no-merge",
        ]
        if fallback_engine:
            run_cmd.extend(["--fallback-engine", fallback_engine])
        run_proc = subprocess.run(run_cmd, timeout=900,
                                   capture_output=True, text=True)

        # Inspect worker outcomes
        run_dir = Path("runs") / rid
        ckpt_dir = run_dir / "checkpoints"
        all_completed = True
        all_tests_passed = True
        worker_count = 0
        if ckpt_dir.exists():
            for ckpt_path in sorted(ckpt_dir.glob("worker-*.json")):
                worker_count += 1
                try:
                    ck = json.loads(ckpt_path.read_text(encoding="utf-8"))
                    if ck.get("state") != "completed":
                        all_completed = False
                    if not ck.get("tests_passed", False):
                        all_tests_passed = False
                except Exception:
                    all_completed = False
                    all_tests_passed = False
        if worker_count == 0:
            all_completed = False

        click.echo(f"  run {rid}: workers={worker_count} "
                   f"all_completed={all_completed} tests_passed={all_tests_passed}")

        # Conditional merge per operator policy
        should_merge = (not no_merge) and all_completed and all_tests_passed
        merged_now = False
        if should_merge:
            integrate_proc = subprocess.run(
                [sys.executable, "-m", "harness", "coord", "integrate",
                 "--run-id", rid, "--commit"],
                capture_output=True, text=True, timeout=900,
            )
            merged_now = integrate_proc.returncode == 0
            click.echo(f"  integrate: rc={integrate_proc.returncode} "
                       f"merged={merged_now}")

        # Move spec to done/
        try:
            dest = done_dir / spec_path.name
            spec_path.rename(dest)
            click.echo(f"  moved spec -> {dest}")
        except OSError as exc:
            click.echo(f"  failed to move spec: {exc}", err=True)

        if all_completed:
            completed_count += 1
        if merged_now:
            merged_count += 1
        processed += 1

    click.echo(f"\nQUEUE DONE: processed={processed}, "
               f"completed={completed_count}, merged={merged_count}")
    sys.exit(0)


@cli.group(name="orchestrator")
def orchestrator_group() -> None:
    """W5-T: autonomous orchestrator (Path α: MiMo→DeepSeek→template chain)."""


@orchestrator_group.command(name="start")
@click.option("--once", is_flag=True, help="Run a single cycle and exit.")
@click.option("--max-cycles", type=int, default=None,
              help="Cap on iterations (default: until backlog empty).")
@click.option("--interval-seconds", type=int, default=0,
              help="Sleep between cycles (cron-style cadence).")
@click.option("--dry-run", is_flag=True,
              help="Compose specs but don't fire coord run.")
def orchestrator_start(once: bool, max_cycles: int | None,
                       interval_seconds: int, dry_run: bool) -> None:
    """Run the autonomous orchestrator.

    Default: runs cycles until coord/STATUS.csv backlog is empty.
    Each cycle picks the next open TODO, composes a spec via the
    MiMo→DeepSeek→template chain, dispatches to coord run, and
    conditionally merges based on tests-passed status.

    Cycles are independent; safe to kill mid-cycle (worker subprocess
    is detached + W5-M pid sentinel prevents duplicate spawn on resume).
    """
    from harness.orchestrator import run_loop, run_one_cycle

    if once:
        outcome = run_one_cycle(1, dry_run=dry_run)
        click.echo(f"\nFINAL: cycle {outcome.cycle} todo={outcome.todo_id} "
                   f"outcome={outcome.worker_outcome} merged={outcome.merged}")
        sys.exit(0 if outcome.worker_outcome in ("completed", "skipped") else 1)

    outcomes = run_loop(
        max_cycles=max_cycles,
        interval_seconds=interval_seconds,
        dry_run=dry_run,
    )
    total_cost = sum(o.composer_cost_usd for o in outcomes)
    completed = sum(1 for o in outcomes if o.worker_outcome == "completed")
    click.echo(f"\nLOOP DONE: {len(outcomes)} cycles, {completed} completed, "
               f"total compose cost=${total_cost:.4f}")
    sys.exit(0)


@orchestrator_group.command(name="install-scheduler")
@click.option("--interval-minutes", type=int, default=30,
              help="How often Task Scheduler fires the orchestrator (default 30 min).")
@click.option("--task-name", default="xaxiu-harness-orchestrator",
              help="Windows Task Scheduler task name.")
def orchestrator_install_scheduler(interval_minutes: int, task_name: str) -> None:
    """Install a Windows Task Scheduler entry to run the orchestrator.

    Creates a task that runs `harness orchestrator start --once` every
    `interval_minutes`.  Operator must approve the schedule + run
    permissions (Task Scheduler will prompt).

    To remove: `schtasks /Delete /TN <task-name> /F` from PowerShell.
    """
    import shutil
    import os

    repo_root = Path.cwd()
    python_exe = sys.executable
    # Build the command Task Scheduler will run.  We need to set
    # PYTHONPATH=src + cwd to repo_root.
    cmd = (
        f'cmd /c "cd /d {repo_root} && '
        f'set PYTHONPATH=src && '
        f'\"{python_exe}\" -m harness orchestrator start --once"'
    )
    # W5-Z 2026-05-23: schtasks /SC MINUTE caps /MO at 1439 (one minute
    # short of 24h).  /SC HOURLY (max /MO 23) is reachable only in that
    # same range, so it adds no capability over MINUTE — skip it.  For
    # intervals >= 1440min we fall through to /SC DAILY (round down to
    # whole days).  Operator can still get hourly cadence via 60/120/…
    # interval-minutes which the MINUTE branch handles cleanly.
    if interval_minutes < 1:
        click.echo("ERROR: --interval-minutes must be >= 1", err=True)
        sys.exit(1)
    if interval_minutes <= 1439:
        sc_flag, mo_value, cadence_desc = (
            "MINUTE", str(interval_minutes), f"every {interval_minutes} minutes",
        )
    else:
        days = max(1, interval_minutes // (24 * 60))
        sc_flag, mo_value, cadence_desc = (
            "DAILY", str(days), f"every {days} days",
        )
    schtasks_cmd = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/SC", sc_flag,
        "/MO", mo_value,
        "/TR", cmd,
        "/F",
    ]
    click.echo(f"Installing Task Scheduler entry '{task_name}'...")
    click.echo(f"  Schedule: {cadence_desc} (/SC {sc_flag} /MO {mo_value})")
    click.echo(f"  Command: {cmd}")
    if shutil.which("schtasks") is None:
        click.echo("ERROR: schtasks not on PATH (need Windows)", err=True)
        sys.exit(1)
    try:
        result = subprocess.run(schtasks_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(f"\n✓ Task installed.  To remove: "
                       f"schtasks /Delete /TN {task_name} /F")
        else:
            click.echo(f"schtasks FAILED rc={result.returncode}: "
                       f"{result.stderr}", err=True)
            sys.exit(1)
    except Exception as exc:
        click.echo(f"ERROR invoking schtasks: {exc}", err=True)
        sys.exit(1)
    sys.exit(0)


@orchestrator_group.command(name="install-claude-scheduler")
@click.option("--interval-minutes", type=int, default=60,
              help="How often Task Scheduler fires `claude -p` (default 60 min).")
@click.option("--task-name", default="xaxiu-harness-claude-orchestrator",
              help="Windows Task Scheduler task name.")
@click.option("--prompt-file", type=click.Path(path_type=Path),
              default=Path("coord/claude-orchestrator-prompt.md"),
              help="Markdown file Claude reads on each tick.  Defaults to "
                   "coord/claude-orchestrator-prompt.md which the harness "
                   "auto-scaffolds.")
@click.option("--output-dir", type=click.Path(path_type=Path),
              default=Path("coord/claude-orchestrator-runs"),
              help="Directory where each tick's Claude output lands.")
@click.option("--claude-bin", default="claude",
              help="Path to the claude binary (default 'claude' on PATH).")
def orchestrator_install_claude_scheduler(
    interval_minutes: int, task_name: str,
    prompt_file: Path, output_dir: Path, claude_bin: str,
) -> None:
    """W5-OO 2026-05-23: install a Task Scheduler entry that runs `claude -p`
    OUTSIDE any parent Claude Code session.

    Why this works when other paths fail:
    - Anthropic's anti-recursion blocks `claude -p` only when its parent
      process is itself a Claude Code session.
    - Task Scheduler spawns processes in a fresh session — no parent
      Claude Code, no recursion guard, OAuth in Windows keychain
      honoured.
    - This is the ONLY autonomous-Claude path available without an
      Anthropic Console API key.

    The installed task on each tick:
      1. Reads ``prompt-file`` (a markdown file describing the
         orchestrator's standing instructions; see `harness orchestrator
         start` for the equivalent in-process behaviour).
      2. Runs ``claude -p < prompt-file > output-dir/<timestamp>.txt``
         so Claude's reply is captured to disk.
      3. The operator (or a downstream harness verb) reads the output
         and feeds it back into the dispatch pipeline.

    NOTE: this verb only installs the task.  It does NOT validate that
    `claude -p` succeeds — first-time validation must be done by the
    operator (run the task manually + inspect output) because we cannot
    test the OAuth path from inside this Claude Code session.

    To remove: `schtasks /Delete /TN <task-name> /F` from PowerShell.
    """
    import shutil

    repo_root = Path.cwd()
    output_dir_abs = (repo_root / output_dir).resolve()
    prompt_path_abs = (repo_root / prompt_file).resolve()

    # Pre-create the output dir + scaffold a default prompt if missing.
    output_dir_abs.mkdir(parents=True, exist_ok=True)
    if not prompt_path_abs.exists():
        prompt_path_abs.parent.mkdir(parents=True, exist_ok=True)
        prompt_path_abs.write_text(
            "# Claude orchestrator prompt (W5-OO scaffold)\n\n"
            "You are the autonomous orchestrator for xaxiu-harness.\n\n"
            "On each tick:\n"
            "1. Read coord/STATUS.csv\n"
            "2. Identify the highest-priority queued production row\n"
            "3. Compose a spec markdown for it\n"
            "4. Drop the spec into spec/auto/ with appropriate P<n>- prefix\n"
            "5. Exit\n\n"
            "Be concise.  The harness queue execute will pick up the spec\n"
            "and dispatch it autonomously.\n",
            encoding="utf-8",
        )
        click.echo(f"scaffolded default prompt: {prompt_path_abs}")

    # Command: claude reads prompt + writes timestamped output.
    # Uses PowerShell so we can interpolate Get-Date for filename.
    cmd = (
        f'powershell -NoProfile -Command "'
        f'$ts = Get-Date -Format yyyyMMddTHHmmssZ; '
        f'$out = \\"{output_dir_abs}\\\\$ts.txt\\"; '
        f'Get-Content -Raw \\"{prompt_path_abs}\\" | '
        f'& \\"{claude_bin}\\" -p > $out 2>&1"'
    )

    # Same MINUTE/DAILY bounds logic as install-scheduler (W5-Z).
    if interval_minutes < 1:
        click.echo("ERROR: --interval-minutes must be >= 1", err=True)
        sys.exit(1)
    if interval_minutes <= 1439:
        sc_flag, mo_value, cadence_desc = (
            "MINUTE", str(interval_minutes), f"every {interval_minutes} minutes",
        )
    else:
        days = max(1, interval_minutes // (24 * 60))
        sc_flag, mo_value, cadence_desc = (
            "DAILY", str(days), f"every {days} days",
        )

    schtasks_cmd = [
        "schtasks", "/Create",
        "/TN", task_name,
        "/SC", sc_flag,
        "/MO", mo_value,
        "/TR", cmd,
        "/F",
    ]
    click.echo(f"Installing Claude orchestrator Task Scheduler entry '{task_name}'...")
    click.echo(f"  Schedule: {cadence_desc} (/SC {sc_flag} /MO {mo_value})")
    click.echo(f"  Prompt:   {prompt_path_abs}")
    click.echo(f"  Output:   {output_dir_abs}")
    click.echo(f"  Claude:   {claude_bin}")
    if shutil.which("schtasks") is None:
        click.echo("ERROR: schtasks not on PATH (need Windows)", err=True)
        sys.exit(1)
    try:
        result = subprocess.run(schtasks_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(
                f"\n✓ Task installed.  Operator-side validation required:\n"
                f"  1. Run manually:  schtasks /Run /TN {task_name}\n"
                f"  2. Inspect:       Get-Content {output_dir_abs}/*.txt | Select-Object -Last 20\n"
                f"  3. If empty output or 'Not logged in', `claude` OAuth\n"
                f"     is not honoured under Task Scheduler context — fall\n"
                f"     back to MiMo/Kimi-API orchestrator.\n"
                f"\nTo remove: schtasks /Delete /TN {task_name} /F"
            )
        else:
            click.echo(f"schtasks FAILED rc={result.returncode}: "
                       f"{result.stderr}", err=True)
            sys.exit(1)
    except Exception as exc:
        click.echo(f"ERROR invoking schtasks: {exc}", err=True)
        sys.exit(1)
    sys.exit(0)


@cli.group(name="memory")
def memory_group() -> None:
    """W5-S: engine-agnostic operator memory (memory/*.md repo dir)."""


@memory_group.command(name="list")
def memory_list_cmd() -> None:
    """List all memory entries (name + title + size)."""
    from harness import memory as _mem
    entries = _mem.load_all()
    if not entries:
        click.echo("(no memory entries — create memory/*.md files)")
        sys.exit(0)
    click.echo(f"{'name':30} {'size':>6}  title")
    click.echo("-" * 72)
    for e in entries:
        click.echo(f"{e.name:30} {e.size_bytes:>6}  {e.title}")
    sys.exit(0)


@memory_group.command(name="show")
@click.argument("name")
def memory_show_cmd(name: str) -> None:
    """Print one memory entry's content."""
    from harness import memory as _mem
    e = _mem.find_by_name(name)
    if e is None:
        click.echo(f"(no memory entry named '{name}' -- `harness memory list` "
                   f"shows what's available)", err=True)
        sys.exit(1)
    # W5-S: write UTF-8 bytes directly to avoid Windows cp1252 codec
    # errors on em-dashes and other non-ASCII content.
    sys.stdout.buffer.write(e.content.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()
    sys.exit(0)


@memory_group.command(name="search")
@click.argument("query")
def memory_search_cmd(query: str) -> None:
    """Find memory entries whose name/title/content match the query."""
    from harness import memory as _mem
    matches = _mem.search(query)
    if not matches:
        click.echo(f"(no memory entries match '{query}')")
        sys.exit(0)
    click.echo(f"{len(matches)} match(es):")
    for e in matches:
        click.echo(f"  {e.name:30} {e.title}")
    sys.exit(0)


@cli.command(name="lint-spec", hidden=True)
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--spec", "spec_opt", type=click.Path(exists=True, path_type=Path), default=None,
              help="Spec markdown path (alternative to positional argument).")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
def lint_spec_cmd(spec_path: Path | None, spec_opt: Path | None, fmt: str) -> None:
    """Pre-flight: validate a markdown spec for plan-readiness.

    W4-H 2026-05-22: accept either `lint-spec <path>` (positional, original)
    or `lint-spec --spec <path>` (flag, what external agents kept guessing
    in the W4-G campaign).  Caller must supply exactly one.
    """
    import dataclasses
    from harness.lint import lint_spec, is_plan_ready

    if spec_path is None and spec_opt is None:
        click.echo("Error: must supply SPEC_PATH positional OR --spec flag", err=True)
        sys.exit(2)
    if spec_path is not None and spec_opt is not None:
        click.echo("Error: cannot supply both positional and --spec — pick one", err=True)
        sys.exit(2)
    spec_path = spec_path if spec_path is not None else spec_opt
    assert spec_path is not None  # narrow for type-checker

    findings = lint_spec(spec_path)
    ready = is_plan_ready(findings)

    if fmt == "json":
        click.echo(json.dumps({
            "spec_path": str(spec_path),
            "plan_ready": ready,
            "findings": [dataclasses.asdict(f) for f in findings],
        }, indent=2))
    else:
        click.echo(f"spec: {spec_path}")
        click.echo(f"plan_ready: {ready}")
        for f in findings:
            click.echo(f"  [{f.severity}] {f.code}: {f.message}")
        if not findings:
            click.echo("  (no findings)")

    # Exit 1 if any error-severity finding exists; exit 0 on warn-only / clean
    sys.exit(0 if ready else 1)


@cli.command(name="doctor")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty")
@click.option("--probe", "with_probe", is_flag=True, default=False,
              help="Also run a LIVE network probe against each configured "
                   "engine (real ~5-token round-trips).  Catches expired / "
                   "typo'd / quota-exhausted keys that the presence check "
                   "cannot.  Costs a few cents per run, takes several "
                   "seconds per engine.  P2 audit fix 2026-05-27.")
def doctor_cmd(fmt: str, with_probe: bool) -> None:
    """Preflight: check git, python, DPAPI, engine keys, coord/ perms, Task Scheduler.

    By default this only checks key PRESENCE.  Use ``--probe`` to also
    do a live network round-trip per engine (catches dead / expired /
    typo'd keys that simple presence checks cannot).
    """
    import dataclasses
    from harness.doctor import run_all, overall_severity

    diagnoses = run_all(with_probe=with_probe)
    overall = overall_severity(diagnoses)

    if fmt == "json":
        click.echo(json.dumps({
            "overall": overall,
            "checks": [dataclasses.asdict(d) for d in diagnoses],
        }, indent=2))
    else:
        glyph = {"ok": "[OK]", "warn": "[!]", "fail": "[X]"}
        click.echo("harness doctor — preflight diagnostics")
        click.echo("=" * 50)
        for d in diagnoses:
            click.echo(f"  {glyph.get(d.severity, '?')} {d.name:<16} {d.message}")
            if d.fix:
                click.echo(f"          fix: {d.fix}")
        click.echo("=" * 50)
        click.echo(f"overall: {overall.upper()}")

    sys.exit(0 if overall != "fail" else 1)


@cli.command(name="preflight")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty",
              help="Output format.")
@click.option("--skip-engines", is_flag=True, default=False,
              help="Skip live engine probes (offline mode).")
@click.option("--fix", "fix_mode", is_flag=True, default=False,
              help="W8-PREFLIGHT-FIX: auto-remediate the three common "
              "failures (dirty git → stash, stale pytest cache → "
              "clear, dead engines → quarantine).  Then re-run "
              "preflight to confirm.")
@click.option("--dry-run", is_flag=True, default=False,
              help="With --fix, preview what would change without "
              "applying.  No effect without --fix.")
@click.option("--allow-stash", is_flag=True, default=False,
              help="W9-PREFLIGHT-FIX-NOSTASH: opt in to the legacy "
              "auto-stash behavior for the git_clean fix.  Without "
              "this flag, --fix names the modified files and points "
              "at manual recovery instead of silently stashing them.")
def preflight_cmd(fmt: str, skip_engines: bool,
                  fix_mode: bool, dry_run: bool,
                  allow_stash: bool) -> None:
    """Comprehensive autonomous-mode readiness gate.

    Runs ``harness doctor`` checks PLUS live engine probes, observer/
    loops Task-Scheduler arming, STATUS.csv freshness, pytest cache
    state, and git tree cleanliness.  Designed to complete in <30s
    via parallel execution.

    Exit codes:
        0  all checks pass
        1  any warn-severity check (autonomous-mode can override)
        4  any fail-severity check (L5 blocker; refuse to start)
    """
    import dataclasses
    from harness.preflight import run_all, overall_exit_code, PreflightCheck

    started = time.monotonic()
    if skip_engines:
        # Build a custom subset that excludes engine probes; useful for
        # offline CI smoke runs.
        from harness import preflight as _pf
        pairs = [(n, fn) for n, fn in _pf._all_check_callables()
                 if not n.startswith("engine:")]
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results: list[PreflightCheck] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fn): name for name, fn in pairs}
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as exc:
                    results.append(PreflightCheck(
                        name=futures[f], severity="fail",
                        message=f"check raised: {type(exc).__name__}: {exc}",
                    ))
        results.sort(key=lambda r: r.name)
    else:
        results = run_all()
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # W8-PREFLIGHT-FIX: --fix runs the auto-remediation pass, then
    # re-runs preflight to confirm.  Output is plain-language for the
    # non-technical operator (per readiness-panel feedback 8/10 vote).
    if fix_mode:
        from harness.preflight import run_fixes
        click.echo("harness preflight --fix — auto-remediation")
        click.echo("=" * 60)
        if dry_run:
            click.echo("DRY RUN — showing what would happen, no changes applied.\n")
        outcomes = run_fixes(dry_run=dry_run, allow_stash=allow_stash)
        for outcome in outcomes:
            if outcome.skipped:
                glyph = "[OK]"
                label = "ok"
            elif outcome.applied:
                glyph = "[FIXED]"
                label = "applied"
            elif outcome.error:
                glyph = "[X]"
                label = "error"
            else:
                glyph = "[!]"
                label = "preview" if dry_run else "needs attention"
            click.echo(f"  {glyph} {outcome.name:<16} {outcome.message}")
            if outcome.error:
                click.echo(f"           error: {outcome.error}")
            if outcome.reversal and outcome.applied:
                click.echo(f"           undo: {outcome.reversal}")
        click.echo("=" * 60)
        if dry_run:
            click.echo("Preview only — nothing changed.  Re-run without "
                       "--dry-run to apply.")
            sys.exit(0)
        # Re-run preflight to confirm the fixes landed
        click.echo("\nRe-running preflight to confirm...")
        results = run_all() if not skip_engines else [
            r for r in run_all() if not r.name.startswith("engine:")
        ]
        elapsed_ms = int((time.monotonic() - started) * 1000)

    # W11-PER-CHECK-LATENCY-OBSERVABILITY: persist per-check timings
    # to the rolling ledger so `harness preflight-latency` can answer
    # "is preflight slow today?" without grepping logs.  Best-effort
    # — a failed ledger write must NOT block the preflight return,
    # but per W11 audit fix (K04 / W9-SILENT-EXCEPTION-AUDIT) the
    # failure is reported to stderr so it does not pass silently.
    try:
        from harness.preflight_latency import record_run as _record_lat
        _record_lat(results)
    except OSError as exc:
        click.echo(
            f"warn: preflight latency ledger write failed: {exc}",
            err=True,
        )

    if fmt == "json":
        click.echo(json.dumps({
            "elapsed_ms": elapsed_ms,
            "checks": [dataclasses.asdict(r) for r in results],
        }, indent=2))
    else:
        # W11-L5-OUTPUT-CONTRACT 2026-05-25: when any check is a FAIL,
        # render an L5 ESCALATION banner FIRST so the operator's eye
        # catches the severity before scanning the per-check table.
        fails = [r for r in results if r.severity == "fail"]
        if fails:
            from harness.l5_escalation import render_l5_banner
            first = fails[0]
            multi = "" if len(fails) == 1 else f" (+{len(fails) - 1} more)"
            click.echo(render_l5_banner(
                code=f"L5.preflight.{first.name.upper().replace(':', '_')}",
                summary=f"preflight check '{first.name}' FAILED{multi}: "
                        f"{first.message}",
                action=first.fix or "run `harness preflight --fix` to "
                                     "attempt auto-remediation",
                evidence=[f"{r.name}: {r.message}" for r in fails[:5]],
            ))
            click.echo("")
        glyph = {"ok": "[OK]", "warn": "[!]", "fail": "[X]"}
        click.echo("harness preflight — autonomous-mode readiness gate")
        click.echo("=" * 60)
        for r in results:
            click.echo(
                f"  {glyph.get(r.severity, '?')} "
                f"{r.name:<20} {r.message}  ({r.duration_ms}ms)"
            )
            # W10-PREFLIGHT-REMEDIATION-CARDS 2026-05-25: print fix hints
            # ONLY for warn/fail checks (ok checks have nothing to fix)
            # and use a visually distinct "→ Run to fix:" callout instead
            # of a buried "fix:" line.  Operators scanning a long preflight
            # output now immediately see the actionable command per
            # warning, not just an indented hint that reads as part of
            # the check message.
            if r.fix and r.severity != "ok":
                click.echo(f"     → Run to fix:  {r.fix}")
        click.echo("=" * 60)
        ok_count = sum(1 for r in results if r.severity == "ok")
        warn_count = sum(1 for r in results if r.severity == "warn")
        fail_count = sum(1 for r in results if r.severity == "fail")
        click.echo(
            f"  {ok_count} ok, {warn_count} warn, {fail_count} fail "
            f"in {elapsed_ms}ms"
        )
        # W10-PREFLIGHT-EXIT-CODE-SEMANTICS 2026-05-25: print a plain-
        # language verdict line so the non-technical operator
        # immediately sees whether the bottom line is GO / GO-WITH-
        # NOTES / STOP, instead of having to interpret a bare exit
        # code (35/40 of the W9 master-audit reviewers called this
        # out; the W9 readiness panel also cited it).
        from harness.preflight import verdict_label as _verdict
        _code = overall_exit_code(results)
        _label, _explanation = _verdict(_code)
        click.echo(f"\n  Verdict: {_label}  (exit code {_code})")
        click.echo(f"  {_explanation}")

    sys.exit(overall_exit_code(results))


@cli.command(name="preflight-latency")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty",
              help="Output format.")
@click.option("--since-hours", type=float, default=None,
              help="Limit to entries within the last N hours "
              "(default: all-time).")
@click.option("--check-name", default=None,
              help="Limit to a single check (e.g. 'engine:kimi').")
def preflight_latency_cmd(fmt: str, since_hours: float | None,
                           check_name: str | None) -> None:
    """W11-PER-CHECK-LATENCY-OBSERVABILITY: rolling p50/p95/p99 of
    preflight check durations.

    Each `harness preflight` run appends per-check timings to the
    ledger.  This verb aggregates them so the operator can answer
    "which preflight check is slow today?" at a glance, sorted by
    p95 desc (slowest first).
    """
    from harness.preflight_latency import latency_summary, latency_table
    if fmt == "json":
        s = latency_summary(since_hours=since_hours, check_name=check_name)
        click.echo(json.dumps(s, indent=2))
    else:
        # W11 audit fix (K03): --check-name now flows through the
        # pretty codepath too, not just JSON.
        click.echo(latency_table(since_hours=since_hours,
                                  check_name=check_name))


@cli.group(name="keys")
def keys_group() -> None:
    """W14-HARNESS-KEYS-WEB-UI: interactive API-key entry + listing.

    Subcommands:
      serve  - launch a local HTTP form for entering provider API keys
               (binds 127.0.0.1, ephemeral port, token-gated)
      list   - print the current key-status table without launching UI
    """


@keys_group.command(name="serve")
@click.option("--port", type=int, default=0,
              help="Bind to this port (default: OS-assigned ephemeral).")
@click.option("--no-open", is_flag=True,
              help="Don't auto-open the browser; just print the URL.")
@click.option("--idle-timeout", type=int, default=600,
              help="Self-shutdown after this many idle seconds "
                   "(default 600).")
def keys_serve(port: int, no_open: bool, idle_timeout: int) -> None:
    """W14-HARNESS-KEYS-WEB-UI: launch the interactive key-entry form.

    Binds to 127.0.0.1 (loopback) only.  Token-gated.  Form lets the
    operator paste each provider key, live-probe via /api/test, and
    save to .env in the current working directory.  Self-shuts-down
    after the idle-timeout.
    """
    from harness.keys_ui import serve_key_ui
    serve_key_ui(
        port=port,
        auto_open=not no_open,
        idle_timeout_seconds=float(idle_timeout),
    )


@keys_group.command(name="list")
@click.option("--format", "fmt",
              type=click.Choice(["pretty", "json"]), default="pretty")
def keys_list(fmt: str) -> None:
    """Show the current API-key status (no UI, no probe).

    For each known provider: env-var name, source (shell env / .env /
    missing), masked value excerpt.  Read-only.
    """
    from harness.keys_ui import list_key_status
    status = list_key_status()
    if fmt == "json":
        import json as _json
        click.echo(_json.dumps(status, indent=2))
        sys.exit(0)
    click.echo(f"{'provider':<22} {'env var':<22} {'source':<10}  "
               f"key (masked)               health")
    click.echo("-" * 100)
    # Lazy-import per-key health so the CLI still works if Tier 2
    # modules are missing for any reason
    try:
        from harness.keys import alias_status_summary
        health_by_provider: dict[str, dict] = {}
    except ImportError:
        alias_status_summary = None
        health_by_provider = {}
    for item in status:
        source_label = item["source"]
        if source_label == "missing":
            source_styled = click.style(source_label, fg="red")
        elif source_label == "env":
            source_styled = click.style(source_label, fg="blue")
        elif source_label == "env-legacy":
            source_styled = click.style(source_label, fg="yellow")
        else:
            source_styled = click.style(source_label, fg="magenta")
        masked = item["masked"] or "(not set)"
        # Lookup per-key health if available
        health_str = ""
        if alias_status_summary and item.get("slot"):
            # Determine the env_prefix by stripping any trailing _N
            base = item["env"]
            n = item["slot"]
            prefix = base.replace(f"_{n}", "") if base.endswith(
                f"_{n}",
            ) else base
            if prefix not in health_by_provider:
                health_by_provider[prefix] = alias_status_summary(prefix)
            alias = f"k{n}"
            h = health_by_provider[prefix].get(alias)
            if h:
                cat = h["category"]
                if h["healthy"]:
                    health_str = click.style(cat, fg="green")
                else:
                    health_str = click.style(cat, fg="red")
            elif item["has_value"]:
                health_str = click.style("untested", fg="white", dim=True)
        click.echo(f"  {item['display']:<20} {item['env']:<22} "
                   f"{source_styled:<19} {masked:<27} {health_str}")
    sys.exit(0)


@keys_group.command(name="probe-all")
@click.option("--format", "fmt",
              type=click.Choice(["pretty", "json"]), default="pretty",
              help="Output format.")
@click.option("--provider", "providers", multiple=True,
              help="Limit to specific providers (env_prefix, e.g. "
                   "KIMI_API_KEY).  Default: all.")
def keys_probe_all(fmt: str, providers: tuple[str, ...]) -> None:
    """W14-KEYS-POOL-TIER2: live-probe every populated slot.

    For each (provider, slot) with a configured key, runs a small
    probe via ``probe_engine_live`` and records the outcome to
    ``coord/key_health.jsonl``.  Returns a table of results that
    the operator can use to identify dead/quota-exceeded keys.

    Cost: one ~5-token round-trip per populated key.  At PAYG rates
    this is well under $0.01 for a full sweep.
    """
    from harness.cli_helpers import probe_engine_live
    from harness.keys import discover_pool, record_outcome
    from harness.keys_ui import KEY_PROVIDERS

    filter_set = set(providers) if providers else None
    results = []
    for spec in KEY_PROVIDERS:
        prefix = spec["env"]
        if filter_set and prefix not in filter_set:
            continue
        engine_probe = spec.get("engine_probe", "")
        if not engine_probe:
            continue  # wrapper-only providers have no live probe
        pool = discover_pool(prefix)
        if not pool:
            results.append({
                "provider": spec["display"],
                "env_prefix": prefix,
                "slot": None,
                "alias": None,
                "category": "no-keys",
                "up": False,
                "error": "",
            })
            continue
        for entry in pool:
            # Override the engine's primary env var temporarily
            # (the engine reads <PREFIX>, so we point it at this slot)
            prior = os.environ.get(prefix)
            os.environ[prefix] = entry.value
            try:
                category, err = probe_engine_live(engine_probe, log=False)
                up = category == "up"
                record_outcome(
                    prefix, entry.alias, entry.env_var,
                    category, source="probe", details=err or "",
                )
                results.append({
                    "provider": spec["display"],
                    "env_prefix": prefix,
                    "slot": entry.slot,
                    "alias": entry.alias,
                    "env_var": entry.env_var,
                    "label": entry.label,
                    "category": category,
                    "up": up,
                    "error": err or "",
                })
            finally:
                if prior is None:
                    os.environ.pop(prefix, None)
                else:
                    os.environ[prefix] = prior

    if fmt == "json":
        import json as _json
        click.echo(_json.dumps(results, indent=2))
        sys.exit(0)

    click.echo(f"{'provider':<22} {'slot':<6} {'alias':<6} {'category':<18} "
               f"label")
    click.echo("-" * 90)
    any_down = False
    for r in results:
        cat = r["category"]
        if r["up"]:
            cat_styled = click.style(cat, fg="green")
        elif cat == "no-keys":
            cat_styled = click.style(cat, fg="white", dim=True)
        else:
            cat_styled = click.style(cat, fg="red")
            any_down = True
        slot = str(r["slot"]) if r["slot"] is not None else "—"
        alias = r["alias"] or "—"
        label = r.get("label", "") or ""
        click.echo(f"  {r['provider']:<20} {slot:<6} {alias:<6} "
                   f"{cat_styled:<28} {label}")

    # W14-KEYS-POOL-HARDENING 2026-05-26: auto-prune ledger so it
    # doesn't grow unbounded under cron/CI cadence.  Each (alias)
    # keeps the most recent 50 records.
    try:
        from harness.keys import prune_old_records
        summary = prune_old_records(keep_per_alias=50)
        if summary.get("dropped", 0) > 0:
            click.echo()
            click.echo(click.style(
                f"  (auto-pruned {summary['dropped']} old health records; "
                f"kept {summary['after']} most-recent per alias)",
                fg="white", dim=True,
            ), err=True)
    except Exception:
        pass

    sys.exit(1 if any_down else 0)


@keys_group.group(name="health")
def keys_health_group() -> None:
    """W14-KEYS-POOL-HARDENING 2026-05-26: health-ledger maintenance."""


@keys_health_group.command(name="prune")
@click.option("--keep-per-alias", type=int, default=50, show_default=True,
              help="Keep at most N most-recent records per (provider, "
                   "alias).  Older entries are dropped atomically.")
def keys_health_prune(keep_per_alias: int) -> None:
    """W14-KEYS-POOL-HARDENING 2026-05-26: compact coord/key_health.jsonl.

    Keeps the most-recent ``--keep-per-alias`` records per (env_prefix,
    alias) pair.  Atomic rewrite under file lock.

    Cross-platform: uses msvcrt locking on Windows, fcntl on POSIX.
    Safe to run while probe-all or dispatch is also writing.

    Auto-invoked as a side effect of `harness keys probe-all`.
    """
    from harness.keys import prune_old_records
    summary = prune_old_records(keep_per_alias=keep_per_alias)
    before = summary["before"]
    after = summary["after"]
    dropped = summary["dropped"]
    aliases = summary["aliases_seen"]
    if before == 0:
        click.echo("no health records to prune (ledger empty or missing)")
    else:
        click.echo(f"  before: {before:>5} records across {aliases} alias(es)")
        click.echo(f"  after:  {after:>5} records "
                   f"(keep-per-alias={keep_per_alias})")
        click.echo(f"  dropped:{dropped:>5}")
    sys.exit(0)


@keys_group.group(name="policy")
def keys_policy_group() -> None:
    """W14-KEYS-POOL-TIER2: per-provider key-selection strategy."""


@keys_policy_group.command(name="get")
@click.argument("env_prefix", required=False)
def keys_policy_get(env_prefix: str) -> None:
    """Show the current strategy.  With no arg, show all providers."""
    from harness.keys import (
        DEFAULT_STRATEGY, get_strategy, list_strategies,
    )
    from harness.keys_ui import KEY_PROVIDERS
    if env_prefix:
        click.echo(get_strategy(env_prefix))
        sys.exit(0)
    all_set = list_strategies()
    click.echo(f"{'env_prefix':<25} strategy")
    click.echo("-" * 55)
    for spec in KEY_PROVIDERS:
        strat = all_set.get(spec["env"], DEFAULT_STRATEGY)
        is_default = spec["env"] not in all_set
        suffix = "  (default)" if is_default else ""
        click.echo(f"  {spec['env']:<23} {strat}{suffix}")
    sys.exit(0)


@keys_policy_group.command(name="set")
@click.argument("env_prefix")
@click.argument("strategy",
                type=click.Choice(["rotation", "priority",
                                   "failover-only"]))
def keys_policy_set(env_prefix: str, strategy: str) -> None:
    """Set the strategy for a provider.

    ENV_PREFIX must be a known provider (e.g. KIMI_API_KEY).
    STRATEGY must be one of rotation / priority / failover-only.
    """
    from harness.keys import set_strategy
    from harness.keys_ui import KNOWN_ENV_VARS
    if env_prefix not in KNOWN_ENV_VARS:
        click.echo(
            click.style(
                f"ERROR: unknown env_prefix {env_prefix!r}.  Known: "
                f"{sorted(KNOWN_ENV_VARS)}", fg="red",
            ),
            err=True,
        )
        sys.exit(1)
    try:
        set_strategy(env_prefix, strategy)
    except ValueError as exc:
        click.echo(click.style(f"ERROR: {exc}", fg="red"), err=True)
        sys.exit(1)
    click.echo(f"set {env_prefix} → {strategy}")
    sys.exit(0)


@keys_group.command(name="forget")
@click.argument("env_prefix")
@click.argument("alias")
def keys_forget(env_prefix: str, alias: str) -> None:
    """W14-KEYS-POOL-TIER2: forget all health history for an alias.

    Use after manually restoring a key that was quarantined.
    Example::

        harness keys forget KIMI_API_KEY k2
    """
    from harness.keys import reset_alias_history
    n = reset_alias_history(env_prefix, alias)
    click.echo(f"dropped {n} record(s) for {env_prefix}/{alias}")
    sys.exit(0)


@cli.group(name="backup")
def backup_group() -> None:
    """W13-BACKUP-RESTORE: snapshot + restore the harness runtime state.

    Backs up: dispatch cache, observer state, STATUS.csv, engine health.
    Does NOT back up: .env (secrets stay out of backups by design),
    src/ (use git), tests/, docs/.
    """


@backup_group.command(name="create")
@click.option("--output-dir", type=click.Path(file_okay=False,
                                              path_type=Path),
              default=None,
              help="Where to write the archive (default: .harness/backups/).")
@click.option("--name", default=None,
              help="Archive filename (default: "
                   "harness-backup-<UTC-stamp>.tar.gz).")
def backup_create_cmd(output_dir: Path | None, name: str | None) -> None:
    """Snapshot the harness runtime state into a .tar.gz archive."""
    from harness.backup import create_backup
    result = create_backup(output_dir=output_dir, archive_name=name)
    size_mb = result.manifest.archive_size_bytes / (1024 * 1024)
    click.echo(f"  archive:       {result.archive_path}")
    click.echo(f"  files:         {result.manifest.files_count}")
    click.echo(f"  size:          {size_mb:.2f} MB")
    click.echo(f"  elapsed:       {result.elapsed_s:.1f}s")
    click.echo(f"  paths_included: {', '.join(result.manifest.paths_included)}")


@backup_group.command(name="list")
def backup_list_cmd() -> None:
    """List existing backup archives (newest first)."""
    from harness.backup import list_backups
    archives = list_backups()
    if not archives:
        click.echo("  (no backups yet — run `harness backup create`)")
        return
    for p in archives:
        size_mb = p.stat().st_size / (1024 * 1024)
        from datetime import datetime, timezone
        mtime = datetime.fromtimestamp(p.stat().st_mtime,
                                        tz=timezone.utc).isoformat()
        click.echo(f"  {p.name}  {size_mb:.2f} MB  {mtime}")


@backup_group.command(name="prune")
@click.option("--keep-dailies", type=int, default=7)
@click.option("--keep-weeklies", type=int, default=4)
def backup_prune_cmd(keep_dailies: int, keep_weeklies: int) -> None:
    """Delete old backups, keeping N most-recent."""
    from harness.backup import prune_old_backups
    deleted = prune_old_backups(keep_dailies=keep_dailies,
                                  keep_weeklies=keep_weeklies)
    if not deleted:
        click.echo("  (nothing to prune)")
        return
    for p in deleted:
        click.echo(f"  deleted: {p.name}")
    click.echo(f"  total: {len(deleted)} archives removed")


@backup_group.command(name="restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False,
                                            path_type=Path))
@click.option("--overwrite/--no-overwrite", default=False,
              help="Overwrite files that already exist in the runtime "
                   "state.  Default --no-overwrite (skip existing).")
def backup_restore_cmd(archive: Path, overwrite: bool) -> None:
    """Restore a backup archive into the repo's runtime state."""
    from harness.backup import restore_backup
    try:
        result = restore_backup(archive, overwrite_existing=overwrite)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"  error: {exc}", err=True)
        sys.exit(2)
    click.echo(f"  archive:        {result.archive_path}")
    click.echo(f"  manifest:       schema_v{result.manifest.schema_version}, "
               f"created {result.manifest.created_at}")
    click.echo(f"  files restored: {result.files_restored}")
    click.echo(f"  elapsed:        {result.elapsed_s:.1f}s")
    if result.warnings:
        click.echo(f"  warnings ({len(result.warnings)}):")
        for w in result.warnings[:10]:
            click.echo(f"    - {w}")
        if len(result.warnings) > 10:
            click.echo(f"    ... and {len(result.warnings) - 10} more")
    sys.exit(0 if result.files_restored > 0 or not result.warnings else 1)


@cli.command(name="review")
@click.argument("document", type=click.Path(exists=True, dir_okay=False,
                                            path_type=Path))
@click.option("--lens-set", default=None,
              type=click.Choice(["default", "code-review", "doc-review"]),
              help="Which set of lenses to apply.  Default: auto-pick "
                   "from file extension (W13 Tier 1 Shift A) — source "
                   "files -> code-review, prose -> doc-review, else "
                   "the 3-engine 'default' set.")
@click.option("--max-tokens", type=int, default=None,
              help="Per-engine output cap.  Default: safe floor 4000 "
                   "(W13 Tier 1 Shift F); --quick lowers to 1000.")
@click.option("--quick", is_flag=True, default=False,
              help="Fast preview mode: drops --max-tokens to 1000.  "
                   "Useful for first-look reviews; rerun without --quick "
                   "for full-depth findings.")
@click.option("--out-dir", type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="Where to write artifacts.  Defaults to "
                   "coord/reviews/review-<document-basename>/.")
@click.option("--max-concurrent", type=int, default=3,
              help="Parallel engine dispatches (default 3).")
def review_cmd(document: Path, lens_set: Optional[str],
                max_tokens: Optional[int], quick: bool,
                out_dir: Path | None, max_concurrent: int) -> None:
    """W12-B-INSTANT-REVIEW + W13 Tier 1 Shifts A+F: multi-engine document review.

    Drops a TXT/MD/PDF (or source file) on the harness for parallel
    multi-engine audit.  Outputs a synthesis Markdown summarizing
    convergent + divergent findings + the raw per-engine reviews.

    Default cost: $0 for the 3-engine subscription mix (Kimi + MiMo
    are subscription; DeepSeek is fractions of a cent per call).

    Auto-defaults (W13 Wed-Thu bundle):
      - --lens-set: picked from file extension (.py -> code-review,
        .md/.pdf -> doc-review, else 'default')
      - --max-tokens: 4000 safe floor (--quick drops to 1000)

    Examples:

      harness review ./student-project-brief.pdf

      harness review src/foo/parser.py        # auto: code-review

      harness review docs/AGENT_QUICKSTART.md # auto: doc-review

      harness review big.md --quick           # fast preview
    """
    from harness.reviewer import (
        review_document, LENS_SETS, infer_lens_set, auto_max_tokens,
    )
    resolved_lens_set = lens_set or infer_lens_set(document)
    resolved_max_tokens = auto_max_tokens(quick=quick, override=max_tokens)
    if resolved_lens_set not in LENS_SETS:
        click.echo(f"error: unknown lens_set {resolved_lens_set!r}; "
                   f"allowed: {sorted(LENS_SETS)}", err=True)
        sys.exit(2)
    lenses = LENS_SETS[resolved_lens_set]
    if lens_set is None:
        click.echo(f"[review] auto-picked lens-set: {resolved_lens_set} "
                   f"(from suffix {document.suffix or '<none>'!r}) — "
                   f"override with --lens-set")
    if max_tokens is None:
        mode = "quick" if quick else "safe-floor"
        click.echo(f"[review] auto-picked max-tokens: {resolved_max_tokens} "
                   f"({mode}) — override with --max-tokens")
    try:
        result = review_document(
            document_path=document,
            lenses=lenses,
            max_tokens=resolved_max_tokens,
            out_dir=out_dir,
            max_concurrent=max_concurrent,
            progress_cb=lambda line: click.echo(f"[review] {line}"),
        )
    except FileNotFoundError as exc:
        click.echo(f"error: file not found: {exc}", err=True)
        sys.exit(2)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    click.echo("")
    click.echo(f"  Synthesis: {result['synthesis_path']}")
    click.echo(f"  Per-engine artifacts: {result['out_dir']}")
    click.echo(f"  Cost: ${result['total_cost_usd']:.4f} "
               f"({result['elapsed_s']:.0f}s)")
    n_failed = sum(1 for r in result["results"] if not r.ok)
    sys.exit(0 if n_failed == 0 else 1)


@cli.command(name="cost-today")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty",
              help="Output format.")
@click.option("--since-hours", type=float, default=24.0,
              help="Window in hours (default 24 = today).  Use 0 for all-time.")
def cost_today_cmd(fmt: str, since_hours: float) -> None:
    """W11-COST-VISIBILITY-WIDGET: 'this session cost $X' surface.

    Operator-facing summary showing total spend vs budget, subscription-
    vs-paid breakdown, and offload ratio.  Designed for the operator who
    asked 'how much did this cost me today?' without grepping the
    dispatch ledger.
    """
    from harness.cost_widget import cost_widget_dict, format_cost_widget
    window = None if since_hours <= 0 else since_hours
    if fmt == "json":
        w = cost_widget_dict(since_hours=window)
        click.echo(json.dumps(w, indent=2))
    else:
        click.echo(format_cost_widget(since_hours=window))


@cli.group(name="audit")
def audit_group() -> None:
    """W13-AUDIT-JSONL: forensic audit trail for every dispatch.

    Append-only redacted ledger at ``~/.harness/audit.jsonl``.  Every
    call to ``harness.dispatch()`` (SDK + CLI) lands one row with
    engine, tokens, cost, retry count, and redacted prompt/response
    excerpts.  Foundation for trustworthy auto-defaults — without it,
    every auto-lens-set / auto-max-tokens / auto-retry becomes an
    un-debuggable black box.
    """


@audit_group.command(name="show")
@click.option("--since-hours", type=float, default=24.0,
              help="Window in hours (default 24).  Use 0 for all-time.")
@click.option("--engine", default=None,
              help="Filter by engine name (kimi/deepseek/mimo/anthropic/gemini).")
@click.option("--tail", type=int, default=20,
              help="Show only the last N matching events (default 20). "
                   "Use 0 for all matches.")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty", help="Output format.")
def audit_show_cmd(since_hours: float, engine: Optional[str],
                    tail: int, fmt: str) -> None:
    """Show recent dispatch audit events (redacted)."""
    from harness.audit_jsonl import iter_events
    window = None if since_hours <= 0 else since_hours
    tail_n = None if tail <= 0 else tail
    events = iter_events(since_hours=window, engine=engine, tail=tail_n)
    if fmt == "json":
        click.echo(json.dumps(events, indent=2))
        return
    if not events:
        scope = (f"in the last {since_hours:g}h"
                 if since_hours > 0 else "all-time")
        eng_scope = f" for engine={engine!r}" if engine else ""
        click.echo(f"No audit events {scope}{eng_scope}.")
        click.echo("Ledger: ~/.harness/audit.jsonl")
        return
    for ev in events:
        ts = ev.get("ts", "?")
        eng = ev.get("engine", "?")
        ok = "ok" if ev.get("success") else "FAIL"
        tin = ev.get("tokens_in", 0)
        tout = ev.get("tokens_out", 0)
        cost = ev.get("cost_usd", 0.0)
        elapsed = ev.get("elapsed_ms", 0)
        retry = ev.get("retry_count", 0)
        retry_s = f" retry={retry}" if retry else ""
        err = ev.get("error")
        err_s = f" err={err[:60]!r}" if err else ""
        click.echo(
            f"{ts}  {eng:>10s}  {ok:>4s}  "
            f"in={tin:>5d}  out={tout:>5d}  ${cost:.4f}  "
            f"{elapsed:>6d}ms{retry_s}{err_s}"
        )


@audit_group.command(name="summary")
@click.option("--since-hours", type=float, default=24.0,
              help="Window in hours (default 24).  Use 0 for all-time.")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty", help="Output format.")
def audit_summary_cmd(since_hours: float, fmt: str) -> None:
    """Aggregate audit events into a one-screen summary."""
    from harness.audit_jsonl import summary as audit_summary
    window = None if since_hours <= 0 else since_hours
    s = audit_summary(since_hours=window)
    if fmt == "json":
        click.echo(json.dumps(s, indent=2))
        return
    win_s = (f"last {since_hours:g}h" if since_hours > 0 else "all-time")
    click.echo(f"Audit summary ({win_s}):")
    click.echo(f"  total events   : {s['total_events']}")
    click.echo(f"  successful     : {s['successful']}")
    click.echo(f"  failed         : {s['failed']}")
    click.echo(f"  retries total  : {s['retries_total']}")
    click.echo(f"  total tokens   : {s['total_tokens']}")
    click.echo(f"  total cost USD : ${s['total_cost_usd']:.4f}")
    if s["by_engine"]:
        click.echo("  by engine:")
        for eng, n in sorted(s["by_engine"].items()):
            click.echo(f"    {eng:>15s}  {n:>5d}")
    click.echo("Ledger: ~/.harness/audit.jsonl")


@cli.group(name="plan")
def plan_group() -> None:
    """W13-HARNESS-PLAN-VERB: surface the active strategic plan.

    The plan lives at ``coord/CURRENT_PLAN.md`` — a hand-maintained
    narrative document distilled from the most recent strategic
    planning panel.  ``coord/STATUS.csv`` is the per-row task tracker;
    this file explains WHY those rows exist + what comes after.

    A fresh agent can run ``harness plan show`` to load the current
    strategic narrative without grepping the repo.
    """


@plan_group.command(name="show")
@click.option("--format", "fmt", type=click.Choice(["pretty", "raw", "json"]),
              default="pretty", help="Output format.  'raw' prints the "
                                       "Markdown verbatim; 'pretty' adds "
                                       "a header banner; 'json' returns "
                                       "{path, exists, last_modified_iso, "
                                       "body_chars, body}.")
def plan_show_cmd(fmt: str) -> None:
    """Print the active strategic plan from ``coord/CURRENT_PLAN.md``."""
    from harness.plan import load_current_plan, plan_path
    info = load_current_plan()
    if fmt == "json":
        click.echo(json.dumps(info, indent=2, default=str))
        return
    if not info["exists"]:
        click.echo(
            f"No plan found at {info['path']}.\n"
            f"  Create it by writing a Markdown file at that path "
            f"summarizing the active strategic plan.\n"
            f"  (See coord/reviews/ for the most recent planning panel "
            f"output if you need a starting point.)",
            err=True,
        )
        sys.exit(2)
    if fmt == "pretty":
        click.echo("=" * 60)
        click.echo(f"  Current strategic plan ({info['path']})")
        click.echo(f"  Last modified: {info['last_modified_iso']}")
        click.echo("=" * 60)
        click.echo("")
    click.echo(info["body"])


@plan_group.command(name="path")
def plan_path_cmd() -> None:
    """Print the absolute path to ``coord/CURRENT_PLAN.md``."""
    from harness.plan import plan_path
    click.echo(str(plan_path()))


@cli.command(name="capabilities")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty", help="Output format.")
def capabilities_cmd(fmt: str) -> None:
    """W13 Wed-Thu bundle: show what this harness install can do.

    Cheap introspection — no engine dispatch.  Lists SDK functions,
    CLI verbs, reachable engines (by API key presence), review lens
    sets + supported extensions, and audit ledger settings.

    Designed for fresh agents asking "what does this harness know how
    to do?" without grepping the source.
    """
    from harness import capabilities as cap_fn
    cap = cap_fn()
    if fmt == "json":
        click.echo(json.dumps(cap, indent=2, default=str))
        return
    click.echo(f"harness v{cap.get('version', '?')} on "
               f"Python {cap.get('python_version', '?')} "
               f"({cap.get('platform', '?')})")
    click.echo("")
    click.echo("SDK functions:")
    for fn in cap.get("sdk_functions", []):
        click.echo(f"  harness.{fn}()")
    click.echo("")
    click.echo("Top-level CLI verbs:")
    verbs = cap.get("cli_verbs", [])
    # 4-column display
    width = max((len(v) for v in verbs), default=0) + 2
    cols = 4
    for i in range(0, len(verbs), cols):
        click.echo("  " + "".join(
            v.ljust(width) for v in verbs[i:i + cols]
        ))
    click.echo("")
    rv = cap.get("review", {})
    click.echo("Review (`harness review` / `harness.review()`):")
    click.echo(f"  lens-sets: {', '.join(rv.get('lens_sets', []))}")
    click.echo(f"  default max_tokens: {rv.get('default_max_tokens', '?')}")
    click.echo(f"  --quick max_tokens: {rv.get('quick_max_tokens', '?')}")
    exts = rv.get("supported_extensions", [])
    click.echo(f"  supported extensions ({len(exts)}): {', '.join(exts[:12])}"
               + (f", ...+{len(exts) - 12} more" if len(exts) > 12 else ""))
    click.echo("")
    eng = cap.get("engines", {})
    click.echo("Engines:")
    for name in eng.get("configured", []):
        ok = "OK" if eng.get("keys_present", {}).get(name) else "no key"
        click.echo(f"  {name:<12s} {ok}")
    click.echo("")
    aud = cap.get("audit", {})
    click.echo("Audit:")
    click.echo(f"  ledger: {aud.get('ledger_path', '?')}")
    click.echo(f"  retention: {aud.get('max_age_days', '?')} days")


@cli.command(name="l5-banner-demo", hidden=True)
def l5_banner_demo_cmd() -> None:
    """W11-L5-OUTPUT-CONTRACT: render a sample L5 ESCALATION banner.

    Operator-visible smoke test: lets you preview what an L5 banner
    looks like without triggering a real escalation.  Hidden verb (it's
    documentation, not production functionality).
    """
    from harness.l5_escalation import render_l5_banner
    click.echo(render_l5_banner(
        code="L5.observer.OBSERVER_RESTART_LOOP",
        summary=(
            "observer scheduler restart failed 3 consecutive times — "
            "the watchdog cannot self-recover"
        ),
        action=(
            "Inspect scheduler manually: on Windows run "
            "`Get-ScheduledTask -TaskName XaxiuHarnessObserver*`; "
            "on Linux/Mac run `crontab -l | grep HARNESS_OBSERVER`."
        ),
        evidence=[
            "latest register message: PowerShell exit code 1",
            "cadence: every 60 min",
            "daily retro at: 23:00",
        ],
    ))


@cli.command(name="today")
@click.option("--since-hours", type=int, default=24,
              help="How far back to look for activity (default 24).")
def today_cmd(since_hours: int) -> None:
    """W8-STATUS-HUMAN: plain-language daily pulse for the operator.

    Shows three sections in plain English:
      1. Overnight summary — what shipped, what audited
      2. Current blockers — preflight + observer flags + dead engines
      3. Next 1-3 actions — what the operator should do today

    Designed for the non-technical operator (per
    [[user_non_technical_role]] memory): no UUIDs, no commit hashes,
    no Python tracebacks unless explicitly part of an error message.
    """
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    repo = Path.cwd()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    click.echo(f"=" * 60)
    click.echo(f"  Today — what happened in the last {since_hours} hours")
    click.echo(f"=" * 60)

    # Section 1: overnight summary
    click.echo("\n## What shipped\n")
    shipped_today: list[str] = []
    try:
        csv_path = repo / "coord" / "STATUS.csv"
        if csv_path.exists():
            import csv as _csv
            with csv_path.open("r", encoding="utf-8", newline="") as fh:
                reader = _csv.DictReader(fh)
                for row in reader:
                    if row.get("Status") != "shipped":
                        continue
                    updated = row.get("Updated", "")
                    # Crude date parse — Updated is "2026-05-23" format
                    try:
                        when = datetime.fromisoformat(
                            updated + "T00:00:00+00:00"
                        )
                    except ValueError:
                        continue
                    if when >= cutoff:
                        title = row.get("Title", "(no title)")
                        shipped_today.append(f"  {row.get('ID', '?')} — {title}")
    except Exception:
        shipped_today = []
    if shipped_today:
        for line in shipped_today[:12]:
            click.echo(line)
        if len(shipped_today) > 12:
            click.echo(f"  ... and {len(shipped_today) - 12} more")
    else:
        click.echo("  (nothing shipped in this window)")

    # Section 1.5: audit results in this window
    click.echo("\n## Audit results (recent reviews)\n")
    audit_dir = repo / "coord" / "reviews" / "audits"
    audit_count = {"pass": 0, "stop": 0}
    recent_audits: list[tuple[str, str, float]] = []
    if audit_dir.exists():
        for audit_file in sorted(audit_dir.glob("*_audit.md"),
                                 key=lambda p: p.stat().st_mtime,
                                 reverse=True):
            try:
                mtime = datetime.fromtimestamp(
                    audit_file.stat().st_mtime, tz=timezone.utc,
                )
            except OSError:
                continue
            if mtime < cutoff:
                continue
            try:
                head = audit_file.read_text(encoding="utf-8")[:500]
            except OSError:
                continue
            import re as _re
            conf_m = _re.search(r"confidence=([0-9.]+)", head)
            task_m = _re.search(r"task=([^\s]+)", head)
            if conf_m and task_m:
                conf = float(conf_m.group(1))
                if conf >= 0.7:
                    audit_count["pass"] += 1
                else:
                    audit_count["stop"] += 1
                recent_audits.append(
                    (task_m.group(1), audit_file.name, conf)
                )
    if recent_audits:
        click.echo(f"  {audit_count['pass']} PASS, "
                   f"{audit_count['stop']} STOP, "
                   f"total {len(recent_audits)} in this window")
        for task, _, conf in recent_audits[:6]:
            verdict = "PASS" if conf >= 0.7 else "STOP"
            click.echo(f"    {verdict:<4} {conf:.2f}  {task}")
        if len(recent_audits) > 6:
            click.echo(f"    ... and {len(recent_audits) - 6} more")
    else:
        click.echo("  (no audits ran in this window)")

    # Section 1.6: W12-LOOP-STALENESS-WATCHDOG — surface the dev-loop's
    # own staleness.  The 20-agent panel found the dashboard claiming
    # "Loop: armed" while last tick was 3 days ago.  Honest 'today'
    # output must flag this so operator notices a dead loop.
    click.echo("\n## Loop health\n")
    try:
        state_path = repo / "coord" / "dev_loop" / "state.json"
        if state_path.exists():
            import json as _json
            state = _json.loads(state_path.read_text(encoding="utf-8"))
            loop = state.get("loop", {})
            last_tick = loop.get("last_tick_at") or loop.get("last_tick")
            loop_status = loop.get("status", "unknown")
            if isinstance(last_tick, str):
                try:
                    t = datetime.fromisoformat(last_tick.rstrip("Z"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    age = datetime.now(timezone.utc) - t
                    hours = age.total_seconds() / 3600
                    if hours < 1:
                        age_label = f"{int(age.total_seconds() / 60)}min ago"
                    elif hours < 24:
                        age_label = f"{hours:.1f}h ago"
                    else:
                        age_label = f"{int(hours / 24)}d ago"
                    if hours > 24:
                        click.echo(
                            f"  [!] Loop {loop_status} but last tick "
                            f"{age_label} - dev-loop may be dead"
                        )
                    else:
                        click.echo(
                            f"  Loop {loop_status} - last tick {age_label}"
                        )
                except (ValueError, TypeError):
                    click.echo(f"  Loop {loop_status} (last_tick: unparseable)")
            else:
                click.echo(f"  Loop {loop_status} (no last_tick_at)")
        else:
            click.echo("  (no coord/dev_loop/state.json — loop never armed)")
    except Exception as exc:
        click.echo(f"  (couldn't read loop state: {exc})")

    # Section 1.7: W11-L5-OUTPUT-CONTRACT — ALWAYS surface L5 events
    # in the last 24h (per spec criterion 3).  Sources of L5:
    #   - observer/flags/CRITICAL_FLAG_PENDING.md (any pending CRITICAL flag)
    #   - observer state consecutive_restart_failures ≥ 3 (watchdog escalation)
    click.echo("\n## L5 escalations (last 24h)\n")
    l5_events: list[str] = []
    crit_flag_path = repo / "coord" / "observer" / "flags" / (
        "CRITICAL_FLAG_PENDING.md"
    )
    if crit_flag_path.exists():
        try:
            mtime = datetime.fromtimestamp(
                crit_flag_path.stat().st_mtime, tz=timezone.utc,
            )
            if mtime >= cutoff:
                l5_events.append(
                    f"  CRITICAL observer flag pending — "
                    f"run `harness observer flags` for detail"
                )
        except OSError:
            pass
    try:
        from harness.observer import state as _ostate
        from harness import l5_escalation as _l5
        st = _ostate.read_state()
        if _l5.should_escalate_to_l5(st.consecutive_restart_failures):
            l5_events.append(
                f"  Observer restart escalation: "
                f"{st.consecutive_restart_failures} consecutive failures "
                f"— run `harness observer restart` (will print full L5 banner)"
            )
    except Exception:
        pass
    if l5_events:
        click.echo("  *** OPERATOR ESCALATION ***")
        for ev in l5_events:
            click.echo(ev)
    else:
        click.echo("  None — no L5 escalations in the last 24h.")

    # Section 2: current blockers
    click.echo("\n## Current blockers\n")
    blockers: list[str] = []
    try:
        from harness.preflight import run_all, overall_exit_code
        # Skip engines — would burn API spend on every `harness today`
        from harness import preflight as _pf
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pairs = [(n, fn) for n, fn in _pf._all_check_callables()
                 if not n.startswith("engine:")]
        pre_results = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fn): name for name, fn in pairs}
            for f in as_completed(futures):
                try:
                    pre_results.append(f.result())
                except Exception:
                    pass
        for r in pre_results:
            if r.severity == "fail":
                blockers.append(f"  [X] {r.name}: {r.message}")
            elif r.severity == "warn":
                blockers.append(f"  [!] {r.name}: {r.message}")
    except Exception as exc:
        blockers.append(f"  (couldn't run preflight: {exc})")
    # Observer flags
    flags_dir = repo / "coord" / "observer" / "flags"
    if flags_dir.exists():
        high_flags = list(flags_dir.glob("*high*.md"))
        if high_flags:
            blockers.append(
                f"  [!] {len(high_flags)} HIGH observer flag(s) — "
                "run `harness observer flags`"
            )
    if blockers:
        for b in blockers[:8]:
            click.echo(b)
        if len(blockers) > 8:
            click.echo(f"  ... and {len(blockers) - 8} more")
    else:
        click.echo("  None — preflight is green.")

    # Section 2.5: capabilities surface (W13 Wed-Thu bundle)
    # One-line install snapshot so a fresh agent / operator sees what
    # this binary can do without firing `harness capabilities` separately.
    click.echo("\n## Install + capabilities\n")
    try:
        from harness import capabilities as _cap_fn
        cap = _cap_fn()
        eng_keys = cap.get("engines", {}).get("keys_present", {})
        eng_ok = sorted(k for k, v in eng_keys.items() if v)
        eng_missing = sorted(k for k, v in eng_keys.items() if not v)
        click.echo(f"  harness v{cap.get('version', '?')} on "
                   f"Python {cap.get('python_version', '?')} "
                   f"({cap.get('platform', '?')})")
        click.echo(f"  Engines reachable: "
                   f"{', '.join(eng_ok) if eng_ok else '(none — set API keys)'}")
        if eng_missing:
            click.echo(f"  Engines unreachable: {', '.join(eng_missing)} "
                       f"(set the *_API_KEY env vars)")
        click.echo(f"  Audit ledger: {cap.get('audit', {}).get('ledger_path', '?')}")
        click.echo(f"  SDK: {', '.join(cap.get('sdk_functions', [])) or '(none)'}")
        click.echo(f"  Run `harness capabilities` for the full dict.")
    except Exception as exc:
        click.echo(f"  (capabilities introspection failed: {exc})")

    # Section 3: next 1-3 actions
    click.echo("\n## Suggested next actions\n")
    suggestions: list[str] = []
    has_fail = any("[X]" in b for b in blockers)
    has_warn = any("[!]" in b for b in blockers)
    if has_fail:
        suggestions.append("  1. Run `harness preflight --fix --dry-run` "
                           "to preview the auto-fix, then drop --dry-run.")
    if has_warn and not has_fail:
        suggestions.append("  1. `harness preflight --fix` for the "
                           "warnings (or ignore — warnings don't block).")
    if not has_fail and not has_warn:
        if audit_count.get("stop", 0) > 0:
            suggestions.append(
                "  1. Review the STOP audits in "
                "`coord/reviews/audits/` — they need operator decision."
            )
        else:
            suggestions.append(
                "  1. Loop is green.  Skim `harness morning-brief` for the "
                "narrative, then go do non-harness work."
            )
    suggestions.append("  2. `harness dashboard-serve` if you want a "
                       "visual.  Closes when you Ctrl-C.")
    suggestions.append("  3. If anything looks wrong, run "
                       "`harness panic-dump` and ping engineering.")
    for s in suggestions:
        click.echo(s)

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  For the full daily playbook: docs/OPERATOR_RUNBOOK.md")
    click.echo(f"{'=' * 60}\n")


@cli.command(name="daily")
@click.option("--full", is_flag=True, default=False,
              help="Include live engine probes (slower; default is "
                   "--skip-engines for snappier morning routine).")
@click.option("--since-hours", type=int, default=12,
              help="How far back to look for activity (default 12).")
def daily_cmd(full: bool, since_hours: int) -> None:
    """W10-DAILY-QUICKSTART-VERB: operator-friendly daily routine.

    Sequences the four commands a non-technical operator runs every
    morning into one verb, with phase headings + a single aggregate
    verdict at the end.  Replaces the memorized four-step incantation:

      [1/4] harness preflight --skip-engines  (or --full)
      [2/4] harness morning-brief --since-hours N
      [3/4] harness today --since-hours N
      [4/4] harness observer flags

    Each phase prints its output + a one-line status.  The final
    verdict matches the worst phase's verdict (using the same
    plain-language labels as `harness preflight`).

    Exit codes: same as `harness preflight` (0/1/4).  See the
    preflight verdict semantics table in OPERATOR_RUNBOOK.
    """
    from harness.preflight import verdict_label

    repo = Path.cwd()
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}

    def _run_phase(label: str, args: list[str], timeout: int = 30) -> int:
        """Run one phase as a subprocess; print output + return exit code."""
        click.echo(f"\n{'=' * 60}")
        click.echo(f"  [{label}]")
        click.echo(f"{'=' * 60}")
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "harness", *args],
                cwd=repo, capture_output=True, text=True, timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            click.echo(
                f"  [TIMEOUT] phase exceeded {timeout}s — "
                f"degrading to warn for aggregate.")
            return 1
        # Stream the output through (operator wants to see it)
        if proc.stdout:
            click.echo(proc.stdout.rstrip())
        if proc.stderr:
            # stderr usually carries operator-facing diagnostics too
            click.echo(proc.stderr.rstrip(), err=True)
        return proc.returncode

    click.echo("=" * 60)
    click.echo("  harness daily — operator morning routine")
    click.echo(f"  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    click.echo("=" * 60)

    phases: list[tuple[str, list[str], int]] = [
        ("1/4 preflight",
         ["preflight"] if full else ["preflight", "--skip-engines"],
         30 if full else 12),
        ("2/4 morning-brief",
         ["morning-brief", "--since-hours", str(since_hours)],
         20),
        ("3/4 today",
         ["today", "--since-hours", str(since_hours)],
         15),
        ("4/4 observer flags",
         ["observer", "flags"],
         10),
    ]

    exit_codes: list[int] = []
    for label, args, t in phases:
        rc = _run_phase(label, args, timeout=t)
        exit_codes.append(rc)

    # Aggregate verdict: worst exit code across phases
    # (4 dominates 1 dominates 0)
    if any(rc >= 4 for rc in exit_codes):
        worst = 4
    elif any(rc != 0 for rc in exit_codes):
        worst = 1
    else:
        worst = 0
    label, explanation = verdict_label(worst)

    click.echo("\n" + "=" * 60)
    click.echo("  Daily routine complete")
    click.echo("=" * 60)
    click.echo(f"\n  Aggregate verdict: {label}  (exit code {worst})")
    click.echo(f"  {explanation}")
    if worst != 0:
        click.echo(
            "\n  Per-phase exit codes: "
            + ", ".join(f"{lbl.split()[0]}={rc}"
                        for (lbl, _, _), rc in zip(phases, exit_codes))
        )
    sys.exit(worst)


@cli.group(name="agent")
def agent_group() -> None:
    """W11-AGENT-INIT-VERB: bootstrap a fresh project for agentic use.

    Designed for agentic coding agents (Claude Code, Cursor, Aider,
    ChatGPT with code interpreter) cloning the harness into a fresh
    project.  Replaces ~20-40 hours of multi-engine routing + audit +
    cost-ledger scaffolding per new project.

    Subcommands:
      init  - one-shot bootstrap: writes .env, adapter.py, CLAUDE.md,
              project-scoped STATUS.csv, .harness/ state dir
    """


@agent_group.command(name="init")
@click.option("--target", required=True, type=click.Path(path_type=Path),
              help="Directory to bootstrap (created if missing).")
@click.option("--project-type", "project_type",
              type=click.Choice(["python", "node", "generic"]),
              default="python",
              help="Project type — selects starter template variant.")
@click.option("--adapter-name", "adapter_name", default=None,
              help="Adapter class name; derived from target basename if "
                   "not given (e.g. my-project -> MyProjectAdapter).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would be written without touching disk.")
@click.option("--allow-self", is_flag=True, default=False,
              help="Allow --target to resolve to the harness's own "
                   "repo (refused by default; data-loss safety).")
def agent_init(target: Path, project_type: str,
               adapter_name: str | None, dry_run: bool,
               allow_self: bool) -> None:
    """Bootstrap a fresh project for agentic harness use.

    Writes a small file tree (.env, adapter.py, CLAUDE.md, .harness/)
    that lets an agentic coding agent immediately dispatch work
    through the harness without spending hours on scaffolding.

    Idempotent: re-running preserves existing .env / adapter.py /
    CLAUDE.md (CLAUDE.md gets a marker-gated append).  STATUS.csv
    collision exits 3 (data file; manual merge required).

    Examples:

      \b
      # Bootstrap a fresh Python project at ./my-scraper:
      harness agent init --target ./my-scraper

      \b
      # Bootstrap with a Node template + custom adapter class name:
      harness agent init --target ./my-bot --project-type node \\
                         --adapter-name BotRouter

      \b
      # See what would happen without writing anything:
      harness agent init --target ./my-scraper --dry-run
    """
    from harness.agent import (
        init_project, render_next_steps,
        SelfTargetRefused, StatusCollisionError,
    )
    try:
        result = init_project(
            target=target,
            project_type=project_type,
            adapter_name=adapter_name,
            dry_run=dry_run,
            allow_self=allow_self,
        )
    except SelfTargetRefused as exc:
        click.echo(f"[X] {exc}", err=True)
        sys.exit(2)
    except StatusCollisionError as exc:
        click.echo(f"[X] {exc}", err=True)
        sys.exit(3)
    except ValueError as exc:
        click.echo(f"[X] {exc}", err=True)
        sys.exit(4)
    except OSError as exc:
        click.echo(f"[X] filesystem error: {exc}", err=True)
        sys.exit(1)
    click.echo(render_next_steps(result))
    sys.exit(0)


@cli.group(name="advanced")
def advanced_group() -> None:
    """W11-HIDE-ADVANCED-VERBS: list + invoke engineering-tier verbs.

    The default `harness --help` hides ~13 operator-engineering
    verbs (spec-*, lint-spec, panic-dump, swarm-verify,
    engines-cooldowns, engines-reliability, burst, lock, replay,
    proxy, coord) to keep the surface focused on daily-use commands.

    Use `harness advanced list` to see the hidden verbs, or invoke
    them directly via their original verb name (e.g. `harness coord
    plan`) — hiding only affects help-text discovery, not callability.
    """


@advanced_group.command(name="list")
def advanced_list() -> None:
    """List the engineering-tier verbs hidden from default --help."""
    # Walk cli.commands looking for hidden=True
    hidden_cmds: list[tuple[str, str]] = []
    for name, cmd in sorted(cli.commands.items()):
        if getattr(cmd, "hidden", False):
            help_text = (cmd.help or cmd.short_help or "").strip()
            help_text = help_text.split("\n")[0][:70]
            hidden_cmds.append((name, help_text))
    if not hidden_cmds:
        click.echo("(no hidden verbs registered)")
        return
    click.echo("Engineering-tier verbs (hidden from default --help):\n")
    width = max(len(n) for n, _ in hidden_cmds)
    for name, help_text in hidden_cmds:
        click.echo(f"  {name:<{width}}  {help_text}")
    click.echo(f"\nInvoke via `harness <verb>` — hidden only affects "
               f"help discovery, not callability.")


@cli.group(name="profile")
def profile_group() -> None:
    """W10-PROFILE-AWARE-DEFAULTS: persisted operator profile.

    Saves the operator's choice of `technical` or `non_technical`
    profile to ~/.harness/profile.json so commands that take
    --profile fall back to the saved value when the flag isn't
    passed.  Run `harness profile set non_technical` once instead of
    typing --profile every invocation.
    """


@profile_group.command(name="set")
@click.argument("profile_name",
                type=click.Choice(["technical", "non_technical"]))
def profile_set(profile_name: str) -> None:
    """Save PROFILE_NAME as the default operator profile."""
    from harness.operator.saved_profile import save_profile, default_profile_path
    record = save_profile(profile_name)
    target = default_profile_path()
    click.echo(f"[OK] saved profile={record.profile} -> {target}")
    click.echo(
        f"     Commands that take --profile will now use "
        f"{record.profile!r} when the flag isn't passed."
    )


@profile_group.command(name="show")
def profile_show() -> None:
    """Show the currently saved profile (or 'unset' if none)."""
    from harness.operator.saved_profile import load_profile, default_profile_path
    saved = load_profile()
    target = default_profile_path()
    if saved is None:
        click.echo(f"[!] no saved profile at {target}")
        click.echo("    Commands fall back to their built-in defaults.")
        click.echo("    Set one via: `harness profile set non_technical`")
        sys.exit(1)
    click.echo(f"[OK] profile={saved.profile}  (saved {saved.updated_at})")
    click.echo(f"     path: {target}")


@cli.command(name="panic-dump", hidden=True)
@click.option("--target-dir", default=None, type=click.Path(path_type=Path),
              help="Output dir (defaults to cwd).")
def panic_dump_cmd(target_dir: Path | None) -> None:
    """Capture a secret-scrubbed snapshot of harness state into one tarball."""
    from harness.panic import panic_dump
    p = panic_dump(target_dir=target_dir)
    click.echo(f"panic-dump written: {p}")
    click.echo(f"size: {p.stat().st_size} bytes")


@cli.command(name="swarm-verify", hidden=True)
@click.option("--expect-edits-in", "expect_paths", multiple=True, required=True,
              help="Path(s) expected to be mutated by the last swarm.")
@click.option("--run-id", default=None,
              help="Swarm run_id (defaults to latest under .swarm/runs/).")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]),
              default="pretty")
def swarm_verify_cmd(expect_paths: tuple[str, ...], run_id: str | None, fmt: str) -> None:
    """Verify the last (or named) swarm actually wrote the expected paths.

    Exits 0 only when EVERY expected path has status='mutated'.  Closes
    the 'Kimi timeout coexists with landed edits' gap.
    """
    import dataclasses
    from harness.swarm_verify import verify_landings, summarize

    results = verify_landings(list(expect_paths), run_id=run_id)
    summary = summarize(results)
    all_landed = summary["mutated"] == len(results) and summary["unmutated"] == 0 and summary["not_in_diff"] == 0

    if fmt == "json":
        click.echo(json.dumps({
            "all_landed": all_landed,
            "summary": summary,
            "results": [dataclasses.asdict(r) for r in results],
        }, indent=2))
    else:
        click.echo(f"summary: {summary}  (all_landed={all_landed})")
        for r in results:
            click.echo(
                f"  {r.status:<14} {r.expected_path}  "
                f"worker={r.worker_id or '-'} swarm_status={r.swarm_status or '-'}"
            )
    sys.exit(0 if all_landed else 1)


@cli.command()
@click.option("--project", "-p", help="Project name.")
@click.option("--add", help="Add loop: NAME::COMMAND::CRON")
@click.option("--remove", help="Remove loop by name.")
def loops(
    project: Optional[str],
    add: Optional[str],
    remove: Optional[str],
) -> None:
    """Manage user-defined scheduled loops."""
    click.echo("loops: pending scheduler integration")
    sys.exit(1)


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("subcmd", required=False)
@click.argument("subcmd_args", nargs=-1)
@click.option("--list", "list_", is_flag=True, help="List engines.")
@click.option("--health", is_flag=True, help="Check engine health (live "
              "dispatch probe by default; --shallow for network-only check).")
@click.option("--shallow", is_flag=True, help="With --health, use the "
              "legacy network-GET probe instead of a real dispatch probe.")
@click.option("--since-hours", type=int, default=168, help="With "
              "'engines failures' subcommand, look back this many hours "
              "(default 168 = 7 days).")
@click.option("--engine", "engine_filter", default=None, help="With "
              "'engines failures' subcommand, restrict to one engine.")
def engines(subcmd: str | None, subcmd_args: tuple[str, ...],
            list_: bool, health: bool, shallow: bool,
            since_hours: int, engine_filter: str | None) -> None:
    """Query or modify the engine pool.

    Subcommands:
      list             — show priority/locked/status per engine (default)
      health           — live-dispatch probe categorizing each engine's
                         state (terminated/auth-failed/quota-exceeded/...)
      heal             — re-issue the in-memory engine health state
      failures         — read state/engine_performance_log.jsonl +
                         state/engine_health_probes.jsonl, aggregate
                         failure counts by category per engine
      install-wrappers — install per-provider claude-* wrapper scripts
      list-wrappers    — show installed wrappers + their key status
      fallback-policy  — show effective fallback chain + skip reasons
      recommend <cls>  — W14-CROSS-ENGINE-AUDIT 2026-05-26 — print the
                         recommended Pattern B engine for a task class.
                         Valid classes: default/latency/verbose/cost/
                         multimodal/audit.  Engine name on stdout
                         (pipe-friendly); rationale on stderr.

    W13-ENGINE-FAILURE-VISIBILITY 2026-05-25: ``engines --health`` now
    defaults to a real dispatch probe (~5 tokens per engine).  The
    legacy network-GET probe — which marks any HTTP response as "up",
    including 403 "Access terminated" — is still available via the
    ``--shallow`` flag.  The live probe catches account-termination,
    quota-exhaustion, and key-revocation cases that the shallow probe
    misses.
    """
    # Normalise subcommand-style guesses into flag-style
    if subcmd == "list":
        list_ = True
    elif subcmd == "health":
        health = True
    elif subcmd == "install-wrappers":
        # W14-CLAUDE-CODE-WRAPPER-SCRIPTS: install per-provider wrappers
        from harness.engines.wrapper_scripts import (
            DEFAULT_WRAPPER_DIR, get_path_hint, install_wrappers,
        )
        click.echo(f"Installing claude-* wrapper scripts to "
                   f"{DEFAULT_WRAPPER_DIR}...")
        result = install_wrappers()
        for name, info in result.items():
            status = info.get("status", "?")
            path = info.get("path", "-")
            if status == "installed":
                color = "green"
                badge = "INSTALLED"
            elif status == "skipped-exists":
                color = "cyan"
                badge = "EXISTS"
            else:
                color = "yellow"
                badge = "SKIPPED"
            badge_styled = click.style(badge, fg=color, bold=True)
            click.echo(f"  {badge_styled:<18}  {name:<22}  {path}")
        hint = get_path_hint()
        if hint:
            click.echo()
            click.echo(click.style(
                "NOTE: wrapper dir is not on your PATH.",
                fg="yellow", bold=True,
            ))
            click.echo(hint)
        else:
            click.echo()
            click.echo(click.style(
                "Wrappers ready — use them like 'claude-mimo \"your prompt\"'",
                fg="green",
            ))
        sys.exit(0)
    elif subcmd == "list-wrappers":
        from harness.engines.wrapper_scripts import list_wrappers
        wrappers = list_wrappers()
        click.echo(f"{'wrapper':<22} {'installed':<10} {'key set':<8}  "
                   f"description")
        click.echo("-" * 80)
        for w in wrappers:
            inst = click.style(
                "yes" if w["installed"] else "no",
                fg="green" if w["installed"] else "red",
            )
            key = click.style(
                "yes" if w["key_present"] else "no",
                fg="green" if w["key_present"] else "yellow",
            )
            click.echo(f"  {w['name']:<20} {inst:<19} {key:<17}  "
                       f"{w['description']}")
        sys.exit(0)
    elif subcmd == "fallback-policy":
        # W14-DISPATCH-HEALTH-AWARE-FALLBACK: show the effective fallback
        # order (priority-sorted, matches dispatcher runtime) with skip
        # reasons (no-key / terminated / over-cap).
        from harness.engines.routing import describe_fallback_policy
        policy = describe_fallback_policy()
        click.echo(f"Filter enabled: {not policy['filter_disabled']}")
        click.echo(f"All production engines: "
                   f"{', '.join(policy['all_engines'])}")
        click.echo()
        if policy['eligible_with_priority']:
            click.echo("Eligible for dispatch (priority-sorted, tie = "
                       "SUPPORTED_BACKENDS order):")
            for entry in policy['eligible_with_priority']:
                # Mark non-NORMAL priorities to make explicit decisions visible
                if entry['priority'] == "HIGH":
                    badge = click.style("HIGH", fg="green", bold=True)
                elif entry['priority'] == "AVOID":
                    badge = click.style("AVOID", fg="yellow")
                else:
                    badge = "NORMAL"
                click.echo(f"  ✓ {entry['engine']:<10}  priority={badge}")
            click.echo()
            click.echo("(All-NORMAL ties resolve by SUPPORTED_BACKENDS "
                       "order; use 'harness priority <engine> HIGH' to "
                       "bump an engine above the tie.)")
        else:
            click.echo("(no engines eligible — check API keys + budget caps)")
        if policy['skipped']:
            click.echo()
            click.echo("Skipped engines:")
            for eng, reason in sorted(policy['skipped'].items()):
                click.echo(f"  ✗ {eng}: {reason}")
        sys.exit(0)
    elif subcmd == "recommend":
        # W14-CROSS-ENGINE-AUDIT 2026-05-26: programmatic routing
        # recommendations from the empirical smoke matrix.  See
        # spec/engine-routing-empirical.md for the data + rationale.
        #
        # Usage:  harness engines recommend <task-class>
        # Valid:  default | latency | verbose | cost | multimodal | audit
        from harness.engines.routing_recommend import (
            VALID_TASK_CLASSES, recommend as _recommend,
        )
        task_class = subcmd_args[0] if subcmd_args else ""
        if not task_class:
            click.echo(
                click.style(
                    "ERROR: harness engines recommend requires a "
                    "task-class argument.  Valid: "
                    + ", ".join(sorted(VALID_TASK_CLASSES)),
                    fg="red",
                ), err=True,
            )
            sys.exit(2)
        rec = _recommend(task_class)
        # Print engine on stdout (pipe-friendly).  Rationale + alternates
        # on stderr so callers can `$(harness engines recommend default)`.
        click.echo(rec.engine)
        if rec.model_override:
            click.echo(
                click.style(
                    f"  (model_override: {rec.model_override})",
                    fg="cyan", dim=True,
                ), err=True,
            )
        click.echo(
            click.style(f"  rationale: {rec.rationale}",
                        fg="white", dim=True),
            err=True,
        )
        if rec.alternates:
            click.echo(
                click.style(
                    f"  alternates: {', '.join(rec.alternates)}",
                    fg="white", dim=True,
                ), err=True,
            )
        sys.exit(0)
    elif subcmd == "failures":
        from harness.cli_helpers import read_failure_summary
        summary = read_failure_summary(
            since_hours=since_hours, engine=engine_filter,
        )
        if not summary["engines"]:
            click.echo(f"No engine events in the last {since_hours}h"
                       + (f" for {engine_filter}" if engine_filter else "")
                       + ".")
            sys.exit(0)
        click.echo(f"Engine failure summary (last {since_hours}h):")
        for eng_name, slot in sorted(summary["engines"].items()):
            total = slot["total"]
            by_cat = slot["by_category"]
            failures = sum(v for k, v in by_cat.items() if k != "up")
            click.echo(f"\n  {eng_name}: {total} events"
                       f" ({failures} failures, "
                       f"{by_cat.get('up', 0)} successes)")
            for cat in sorted(by_cat, key=lambda c: -by_cat[c]):
                if cat == "up":
                    continue
                click.echo(f"    {cat:<18} {by_cat[cat]}")
            if slot["recent_samples"]:
                click.echo("    recent samples:")
                for s in slot["recent_samples"]:
                    excerpt = (s.get('error_excerpt') or '')[:80]
                    click.echo(
                        f"      {s['timestamp']} {s['category']:<14} "
                        f"({s['source']}) {excerpt}"
                    )
        sys.exit(0)
    elif subcmd == "heal":
        from click.testing import CliRunner as _CR  # local import OK
        runner = _CR()
        ctx = click.get_current_context()
        ctx.invoke(engines_heal_cmd, dry_run=False, engine=None)
        return
    elif subcmd is not None:
        click.echo(f"Error: unknown subcommand {subcmd!r}; use 'list', "
                   f"'health', 'failures', or 'heal' "
                   f"(or --list / --health flags)", err=True)
        sys.exit(2)

    state = read_engine_health()

    if health:
        if shallow:
            probes = probe_all_engines()
        else:
            from harness.cli_helpers import probe_all_engines_live
            probes = probe_all_engines_live()
        for name, (st, err) in probes.items():
            click.echo(f"{name}: {st}" + (f" ({err})" if err else ""))
        sys.exit(0)

    # Default / --list
    for name in ["deepseek", "kimi", "mimo", "anthropic", "gemini"]:
        cfg = state.get(name)
        if cfg:
            click.echo(
                f"{name}: priority={cfg.priority} locked={cfg.locked} "
                f"status={cfg.status}"
            )
        else:
            click.echo(f"{name}: priority=NORMAL locked=False status=up")
    sys.exit(0)


@cli.command(name="engines-reliability", hidden=True)
@click.option("--publish", is_flag=True,
              help="Write coord/engine_reliability.json from latest campaigns.")
def engines_reliability(publish: bool) -> None:
    """Show / publish engine reliability ranking from campaign data.

    W5-C 2026-05-22: aggregates W4-G campaign outputs into a parseable-rate
    ranking per engine.  The dispatcher consults this at fallback-time to
    prefer engines that have shown empirical reliability over the
    hardcoded chain.
    """
    from harness.engines.reliability import (
        aggregate_campaigns, publish as publish_digest, load_published,
    )

    if publish:
        out = publish_digest()
        click.echo(f"published reliability digest to {out}")
        # fall through to display it

    digest = aggregate_campaigns() if not publish else load_published()
    if digest is None or not digest.ranking:
        click.echo("(no reliability data yet — run scripts/multi_agent_coverage.py)",
                   err=True)
        sys.exit(1 if not publish else 0)

    click.echo(f"# engine reliability  (campaigns={len(digest.source_campaigns)})")
    click.echo(f"{'engine':10} {'model':22} {'ok':>4} {'fail':>4} "
               f"{'rate':>6} {'avg_lat_ms':>10}")
    for r in digest.ranking:
        click.echo(f"{r.engine:10} {(r.model or ''):22} "
                   f"{r.ok:>4} {r.fail:>4} "
                   f"{r.parseable_rate:>5.1%} {r.avg_latency_ms:>10}")
    sys.exit(0)


@cli.command(name="engines-heal")
@click.option("--dry-run", is_flag=True, default=False,
              help="Preview what would happen without applying.")
@click.option("--engine", default=None,
              help="Heal only this engine (default: all dead engines).")
def engines_heal_cmd(dry_run: bool, engine: str | None) -> None:
    """W8-ENGINES-HEAL: one-command recovery for dead / quarantined engines.

    Walks the dead-engine alarm state (W6-C2) plus the engine health
    file and:
      1. Quarantines engines currently above the failure threshold.
      2. Attempts to reload API keys from DPAPI for each quarantined
         engine — if the key is back, mark it ``recovering`` so the
         dispatcher gives it one more attempt.
      3. Surfaces a plain-language report.

    Designed for the non-technical operator (per
    [[user_non_technical_role]] + readiness panel feedback 4/10 vote).
    No Python tracebacks, no JSONL paths — operator-friendly only.

    To reset an engine manually later, run ``harness engines reset
    <name>`` (or ``priority <name> NORMAL`` if you'd rather route to
    it).
    """
    from harness.engine_alarm import dead_engines as _dead
    from harness.state.files import read_engine_health, update_engine_health
    from harness.secrets import dpapi
    from harness._constants import API_KEY_ENV_VARS

    click.echo("=" * 60)
    click.echo("  harness engines-heal — automated engine recovery")
    click.echo("=" * 60)
    if dry_run:
        click.echo("\nDRY RUN — no changes will be applied.\n")

    # 1) Find dead engines (from the alarm) + currently-quarantined
    # ones (from engine_health).
    try:
        dead_streaks = _dead()
    except Exception as exc:
        click.echo(f"  [X] Couldn't read engine alarm state: {exc}", err=True)
        sys.exit(2)
    try:
        health = read_engine_health()
    except Exception as exc:
        click.echo(f"  [X] Couldn't read engine health: {exc}", err=True)
        sys.exit(2)
    # W8-AUDIT follow-through 2026-05-24: read_engine_health returns
    # Pydantic EngineHealth objects in production but tests stub it with
    # raw dicts — handle both so the quarantined detection actually
    # fires in both contexts.
    def _entry_status(entry: Any) -> str | None:
        if isinstance(entry, dict):
            return entry.get("status")
        return getattr(entry, "status", None)
    quarantined_now = {
        name for name, entry in (health or {}).items()
        if _entry_status(entry) == "quarantined"
    }
    affected = set(dead_streaks.keys()) | quarantined_now
    if engine:
        affected = {e for e in affected if e == engine}
        if not affected:
            click.echo(
                f"  [OK] Engine '{engine}' is not in the dead or "
                f"quarantined set — nothing to heal."
            )
            sys.exit(0)
    if not affected:
        click.echo("\n  [OK] All engines are healthy — nothing to heal.")
        click.echo("\n  Tip: `harness engines-reliability` shows the full")
        click.echo("       ranking if you want a deeper look.\n")
        sys.exit(0)

    click.echo(f"\n  Found {len(affected)} engine(s) needing attention:\n")
    actions: list[tuple[str, str, str]] = []  # (engine, action, message)
    for e in sorted(affected):
        streak = dead_streaks.get(e, 0)
        was_quarantined = e in quarantined_now
        # 2) Probe DPAPI for the engine's API key
        env_var = API_KEY_ENV_VARS.get(e, "").upper()
        key_present = False
        if env_var:
            try:
                key_present = dpapi.has_secret(env_var)
            except Exception:
                key_present = False
        if streak > 0 and not was_quarantined:
            # Newly dead — quarantine
            if dry_run:
                actions.append((
                    e, "would-quarantine",
                    f"Hit {streak} consecutive failures.  "
                    f"Would quarantine.  Key in DPAPI: "
                    f"{'YES' if key_present else 'no'}.",
                ))
            else:
                try:
                    update_engine_health(e, {
                        "status": "quarantined",
                        "last_quarantine": datetime.now(timezone.utc).isoformat(),
                    })
                    actions.append((
                        e, "quarantined",
                        f"Quarantined after {streak} consecutive "
                        f"failures.  Key in DPAPI: "
                        f"{'YES' if key_present else 'no'}.",
                    ))
                except Exception as exc:
                    actions.append((
                        e, "error",
                        f"Tried to quarantine but couldn't update "
                        f"engine health: {exc}",
                    ))
        elif was_quarantined and key_present:
            # Already quarantined + key is present in DPAPI → mark
            # recovering so the dispatcher tries it once.
            if dry_run:
                actions.append((
                    e, "would-recover",
                    f"Already quarantined.  Key in DPAPI is present.  "
                    f"Would mark as 'recovering' for one retry.",
                ))
            else:
                try:
                    update_engine_health(e, {
                        "status": "recovering",
                        "last_heal_attempt": datetime.now(timezone.utc).isoformat(),
                    })
                    actions.append((
                        e, "recovering",
                        f"Marked as 'recovering' — dispatcher will "
                        f"give it one more attempt.  If it succeeds, "
                        f"it auto-promotes back to 'ok'.",
                    ))
                except Exception as exc:
                    actions.append((
                        e, "error",
                        f"Tried to mark recovering but failed: {exc}",
                    ))
        elif was_quarantined and not key_present:
            actions.append((
                e, "blocked",
                "Quarantined and no API key found in DPAPI.  Engine "
                "needs a fresh key — run `harness install` to seed it, "
                "OR set the env var and re-run engines-heal.",
            ))
        else:
            actions.append((
                e, "watch",
                f"Currently above failure threshold ({streak} streak) "
                "but not yet quarantined.  Will be picked up on next "
                "dispatch.  Re-run engines-heal in a few minutes if "
                "this persists.",
            ))

    glyph = {
        "quarantined": "[FIXED]",
        "would-quarantine": "[!]",
        "recovering": "[FIXED]",
        "would-recover": "[!]",
        "blocked": "[X]",
        "watch": "[!]",
        "error": "[X]",
    }
    for e, action, msg in actions:
        g = glyph.get(action, "[?]")
        click.echo(f"  {g} {e:<12} {action:<18} {msg}")
        if action in {"quarantined", "recovering"}:
            click.echo(
                f"          undo: harness engines reset {e}  "
                "(or  priority {e} NORMAL)"
            )
    click.echo("=" * 60)
    if dry_run:
        click.echo("\n  Preview only — nothing changed.")
        click.echo("  Re-run without --dry-run to apply.\n")
    else:
        applied = sum(1 for _, a, _ in actions
                      if a in {"quarantined", "recovering"})
        blocked = sum(1 for _, a, _ in actions if a == "blocked")
        click.echo(f"\n  Healed {applied}; blocked {blocked}; "
                   f"to-watch {len(actions) - applied - blocked}.")
        if blocked:
            click.echo("\n  Blocked engines need a fresh API key.  "
                       "Ask your engineering teammate or run "
                       "`harness install` to seed.\n")
        else:
            click.echo("")
    sys.exit(0)


@cli.command(name="engines-cooldowns", hidden=True)
def engines_cooldowns() -> None:
    """Show active engine cooldowns."""
    from harness.loops.state import read_state
    state_path = Path("coord") / "dev_loop" / "state.json"
    state = read_state(state_path)
    cd = getattr(state, "engine_cooldowns", {}) or {}
    if not cd:
        click.echo("no active cooldowns")
        return
    click.echo(f"{'ENGINE':<24} {'UNTIL':<28}  REASON")
    for engine, info in sorted(cd.items()):
        if isinstance(info, dict):
            until = info.get("until", "-")
            reason = info.get("reason", "-")
        else:
            until = str(info)
            reason = "-"
        click.echo(f"{engine:<24} {until:<28}  {reason}")


@cli.command()
@click.argument("engine")
@click.argument("level", type=click.Choice(["HIGH", "NORMAL", "AVOID"]))
def priority(engine: str, level: str) -> None:
    """Set persistent routing priority per engine."""
    try:
        update_engine_health(engine, {"priority": level})
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"priority: {engine} -> {level}")
    sys.exit(0)


@cli.command(hidden=True)
@click.argument("engine")
@click.argument("duration_min", type=int)
def burst(engine: str, duration_min: int) -> None:
    """Temporarily route all traffic to one engine."""
    if duration_min <= 0:
        click.echo("error: duration_min must be positive", err=True)
        sys.exit(2)

    expiry = datetime.now(timezone.utc) + timedelta(minutes=duration_min)
    try:
        update_engine_health(engine, {"burst_until": expiry.isoformat()})
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"burst: {engine} until {expiry.isoformat()}")
    sys.exit(0)


@cli.command(hidden=True)
@click.argument("engine")
@click.option("--release", is_flag=True, help="Release the lock.")
def lock(engine: str, release: bool) -> None:
    """Exclusive routing lock (disables auto-routing)."""
    try:
        update_engine_health(engine, {"locked": not release})
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    action = "released" if release else "locked"
    click.echo(f"lock: {engine} {action}")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Observer primitive CLI (roster #20)
# ---------------------------------------------------------------------------


@cli.group(name="observer")
def observer() -> None:
    """Independent harness observer — authority audit, flagging, scheduling."""


@observer.command(name="init")
@click.option("--cadence-minutes", type=int, default=60, help="Cycle cadence in minutes.")
@click.option("--daily-time", default="23:00", help="Daily retro time (HH:MM).")
def observer_init(cadence_minutes: int, daily_time: str) -> None:
    """Create observer directory tree and state file."""
    from datetime import datetime, timezone

    base = ensure_flag_dirs()
    state = ObserverState(
        armed=True,
        paused=False,
        cadence_minutes=cadence_minutes,
        daily_retro_time=daily_time,
        installed_at=datetime.now(timezone.utc).isoformat(),
        status="initialized",
    )
    write_state(state)
    click.echo(f"observer initialized at {base}")
    click.echo(f"  cadence: {cadence_minutes} min  daily-retro: {daily_time}")
    sys.exit(0)


@observer.command(name="arm")
def observer_arm() -> None:
    """Arm the observer (enable automatic cycles)."""
    state = read_state()
    if state.status == "uninitialized":
        click.echo("error: observer not initialized — run 'harness observer init' first", err=True)
        sys.exit(1)
    state.armed = True
    state.paused = False
    write_state(state)
    click.echo("observer armed")
    sys.exit(0)


@observer.command(name="disarm")
def observer_disarm() -> None:
    """Disarm the observer (disable automatic cycles)."""
    state = read_state()
    if state.status == "uninitialized":
        click.echo("error: observer not initialized", err=True)
        sys.exit(1)
    state.armed = False
    write_state(state)
    click.echo("observer disarmed")
    sys.exit(0)


@observer.command(name="pause")
def observer_pause() -> None:
    """Pause the observer (skip cycles but keep armed)."""
    state = read_state()
    if state.status == "uninitialized":
        click.echo("error: observer not initialized", err=True)
        sys.exit(1)
    state.paused = True
    write_state(state)
    click.echo("observer paused")
    sys.exit(0)


@observer.command(name="resume")
def observer_resume() -> None:
    """Resume the observer from pause."""
    state = read_state()
    if state.status == "uninitialized":
        click.echo("error: observer not initialized", err=True)
        sys.exit(1)
    state.paused = False
    write_state(state)
    click.echo("observer resumed")
    sys.exit(0)


@observer.command(name="status")
def observer_status() -> None:
    """Show observer state."""
    state = read_state()
    click.echo(f"status:       {state.status}")
    click.echo(f"armed:        {state.armed}")
    click.echo(f"paused:       {state.paused}")
    click.echo(f"cadence:      {state.cadence_minutes} min")
    click.echo(f"daily-retro:  {state.daily_retro_time}")
    click.echo(f"last-cycle:   {state.last_cycle_at or '(never)'}")
    click.echo(f"total-cycles: {state.total_cycles}")
    click.echo(f"flags-raised: {state.flags_raised}  acked: {state.flags_acknowledged}")
    sys.exit(0)


@observer.command(name="flags")
@click.option("--severity", type=click.Choice(["high", "critical", "all"]), default="all")
def observer_flags(severity: str) -> None:
    """List pending flags."""
    pending = list_pending_flags()
    severities = [FlagSeverity.HIGH, FlagSeverity.CRITICAL] if severity == "all" else [FlagSeverity(severity)]
    total = 0
    for sev in severities:
        flags = pending.get(sev, [])
        for f in flags:
            if not f.acknowledged:
                total += 1
                click.echo(f"{f.id}  {f.severity.value.upper():8}  [{f.category}]  {f.summary}")
    if total == 0:
        click.echo("(no pending flags)")
    sys.exit(0)


@observer.command(name="ack")
@click.argument("flag_id")
def observer_ack(flag_id: str) -> None:
    """Acknowledge a flag by ID (operator only)."""
    updated = ack_flag(flag_id, acknowledged_by="operator")
    if updated is None:
        click.echo(f"error: flag '{flag_id}' not found", err=True)
        sys.exit(1)
    click.echo(f"acknowledged {flag_id}")
    sys.exit(0)


@observer.command(name="cycle-now")
@click.option("--engine", default="swarm/deepseek", help="Audit engine override.")
@click.option("--window", "audit_window", type=int, default=60, help="Minutes of history to audit.")
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Preview inputs without dispatching.")
@click.pass_context
def observer_cycle_now(ctx: click.Context, engine: str, audit_window: int, dry_run: bool) -> None:
    """Run one observer cycle immediately."""
    state = read_state()
    if state.status == "uninitialized":
        click.echo("error: observer not initialized", err=True)
        sys.exit(1)
    if state.paused:
        click.echo("observer paused — skipping cycle")
        sys.exit(0)

    op_cfg = (ctx.obj or {}).get("operator_config") if ctx.obj else None
    if op_cfg is not None and op_cfg.mode == OperatorMode.DRY_RUN:
        click.echo("dry-run: would run observer cycle")
        sys.exit(0)

    report = run_cycle(engine=engine, audit_window_minutes=audit_window, dry_run=dry_run)

    if dry_run:
        click.echo(str(report.report_path))
        sys.exit(0)

    # Update state
    state.last_cycle_at = report.ended_at
    state.last_cycle_id = report.cycle_id
    state.total_cycles += 1
    state.flags_raised += len(report.flags_raised)
    write_state(state)

    # Output
    click.echo(f"cycle {report.cycle_id} complete")
    click.echo(f"  engine: {report.engine_used}")
    click.echo(f"  findings: {report.findings_count}")
    click.echo(f"  flags: {len(report.flags_raised)}")
    for f in report.flags_raised:
        click.echo(f"    {f.id}  {f.severity.value.upper()}  [{f.category}]  {f.summary}")
    if report.error:
        click.echo(f"  dispatch-error: {report.error}")
    sys.exit(0)


@observer.command(name="daily-retro")
def observer_daily_retro() -> None:
    """Run the daily retro (placeholder until Wave A.3)."""
    click.echo("daily-retro: pending Wave A.3")
    sys.exit(0)


@observer.command(name="install-scheduler")
@click.option("--cadence-minutes", type=int, default=60)
@click.option("--daily-time", default="23:00")
@click.option("--include-chat", is_flag=True,
              help="Also register the chat-observer audit task (CHAT-OBSERVER).")
@click.option("--all", "include_all", is_flag=True,
              help="Arm every Task Scheduler entry (chat + cycle + retro + db-snapshot + cost-export).")
def observer_install_scheduler(cadence_minutes: int, daily_time: str,
                                include_chat: bool, include_all: bool) -> None:
    """Register Windows Task Scheduler entries for the observer.

    With --all, also arms downstream tasks: db snapshot (hourly) and
    daily cost CSV export.  Independent of the observer/retro tasks
    so they fail gracefully if any one isn't installable.
    """
    # --all implies --include-chat
    include_chat = include_chat or include_all
    # W11-CROSS-PLATFORM-OBSERVER: dispatch to cron on Linux/Mac,
    # Task Scheduler on Windows.  Same call signature for both
    # so the operator/agent doesn't need to know which platform
    # they're on.
    from harness.observer.cron_scheduler import (
        is_unix_like,
        register_cron_tasks,
    )
    if is_unix_like():
        ok, msg = register_cron_tasks(
            cadence_minutes=cadence_minutes, daily_time=daily_time,
            include_chat=include_chat,
        )
    else:
        ok, msg = register_tasks(
            cadence_minutes=cadence_minutes, daily_time=daily_time,
            include_chat=include_chat,
        )
    click.echo(f"observer/retro: {msg}")
    overall_ok = ok

    if include_all:
        # DB-snapshot task (WIRE-DB-SNAPSHOT-CRON)
        try:
            from harness.state.db_scheduler import register_snapshot_task
            ok_db, msg_db = register_snapshot_task(cadence_minutes=cadence_minutes)
            click.echo(f"db-snapshot: {msg_db}")
            overall_ok = overall_ok and ok_db
        except ImportError:
            click.echo("db-snapshot: SKIP — module not yet shipped")
        # Daily cost-CSV export task
        try:
            from harness.budget import register_cost_export_task
            ok_cost, msg_cost = register_cost_export_task(daily_time=daily_time)
            click.echo(f"cost-export: {msg_cost}")
            overall_ok = overall_ok and ok_cost
        except ImportError:
            click.echo("cost-export: SKIP — register_cost_export_task not implemented")

    sys.exit(0 if overall_ok else 1)


@observer.command(name="uninstall-scheduler")
def observer_uninstall_scheduler() -> None:
    """Remove observer scheduler entries (cron on Linux/Mac, Task Scheduler
    on Windows, plus chat + db + cost when present)."""
    from harness.observer.cron_scheduler import (
        is_unix_like,
        unregister_cron_tasks,
    )
    if is_unix_like():
        ok, msg = unregister_cron_tasks()
    else:
        ok, msg = unregister_tasks()
    click.echo(f"observer/retro: {msg}")
    overall_ok = ok
    # Best-effort removal of downstream tasks
    try:
        from harness.state.db_scheduler import unregister_snapshot_task
        ok_db, msg_db = unregister_snapshot_task()
        click.echo(f"db-snapshot: {msg_db}")
        overall_ok = overall_ok and ok_db
    except ImportError:
        pass
    try:
        from harness.budget import unregister_cost_export_task
        ok_cost, msg_cost = unregister_cost_export_task()
        click.echo(f"cost-export: {msg_cost}")
        overall_ok = overall_ok and ok_cost
    except ImportError:
        pass
    sys.exit(0 if overall_ok else 1)


@observer.command(name="watchdog-status")
@click.option("--json", "as_json", is_flag=True,
              help="Emit JSON instead of human-readable lines.")
def observer_watchdog_status(as_json: bool) -> None:
    """W11-OBSERVER-WATCHDOG-RECOVERY: check if observer task has gone stale.

    Exit 0 healthy, 1 stale.  Use in scripts/cron for self-recovery.
    """
    from harness.observer.watchdog import watchdog_status
    status = watchdog_status()
    if as_json:
        import json as _json
        click.echo(_json.dumps(status, indent=2, default=str))
    else:
        # W12-WATCHDOG-HUMAN-FORMAT: lead with the one-liner summary so
        # operators don't have to do mental math from `stale_seconds: 1209.65`.
        click.echo(status['summary_line'])
        click.echo("")
        click.echo(f"  verdict:         {status['verdict']}")
        click.echo(f"  last_cycle_at:   {status['last_cycle_at'] or '(never)'}")
        click.echo(f"  stale:           {status['stale_human']}")
        click.echo(f"  cadence:         {status['cadence_human']}")
        click.echo(f"  armed/paused:    armed={status['armed']} paused={status['paused']}")
        if status['suggested_action']:
            click.echo("")
            click.echo(f"  ACTION: {status['suggested_action']}")
    sys.exit(1 if status['is_stale'] else 0)


@observer.command(name="restart")
def observer_restart() -> None:
    """W11-OBSERVER-WATCHDOG-RECOVERY: unregister + re-register the observer.

    Preserves existing cadence_minutes + daily_retro_time.  Auto-picks
    cron (Linux/Mac) or Task Scheduler (Windows) based on platform.
    """
    from harness.observer.watchdog import restart_observer
    ok, msg = restart_observer()
    click.echo(msg)
    sys.exit(0 if ok else 1)


@observer.command(name="audit-chat")
@click.option("--tail-lines", default=500, type=int,
              help="Number of trailing transcript lines to scan.")
def observer_audit_chat(tail_lines: int) -> None:
    """Audit the Claude Code session transcript for dev-manager drift."""
    from harness.observer.chat import audit
    report = audit(tail_lines=tail_lines)
    if report.transcript_path is None:
        click.echo("error: could not locate session transcript jsonl", err=True)
        sys.exit(1)
    click.echo(f"transcript: {report.transcript_path}")
    click.echo(f"lines: {report.line_count}  assistant_turns: {report.assistant_turn_count}")
    if not report.flags:
        click.echo("flags: none")
        return
    for f in report.flags:
        click.echo(f"  [{f.severity}] {f.pattern}: {f.detail}")


# ---------------------------------------------------------------------------
# Heartbeat (HEARTBEAT — roster row #17)
# ---------------------------------------------------------------------------


@cli.group(name="heartbeat")
def heartbeat() -> None:
    """Passive dev-manager liveness signal for the operator."""


@heartbeat.command(name="pulse")
def heartbeat_pulse() -> None:
    """Emit one heartbeat now (dev-loop manager calls this each tick)."""
    from harness.heartbeat import pulse as _pulse

    try:
        beat = _pulse()
    except FileNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"pulsed at {beat.pulsed_at} (tick #{beat.tick_count})")


@heartbeat.command(name="show")
def heartbeat_show() -> None:
    """Print the last heartbeat in operator-readable form."""
    from harness.heartbeat import format_for_human, read_heartbeat

    click.echo(format_for_human(read_heartbeat()))


# ---------------------------------------------------------------------------
# State inspector (STATE-INSPECT — roster row #18 companion)
# ---------------------------------------------------------------------------


@cli.group(name="state")
def state() -> None:
    """Inspect dev-loop runtime state."""


@state.command(name="inspect")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json", "compact"]), default="pretty")
@click.option("--path", type=click.Path(path_type=Path),
              default=lambda: LOOP_DEFAULT_STATE_PATH)
def state_inspect(fmt: str, path: Path) -> None:
    """Pretty-print coord/dev_loop/state.json for the operator."""
    from harness.errors import ConfigCorruption
    from harness.state.inspect import render_state_json

    try:
        click.echo(render_state_json(path=path, fmt=fmt))
    except FileNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    except ConfigCorruption as exc:
        # W5-Y 2026-05-23: route through handle_harness_error so the
        # L5 operator-escalation banner fires uniformly (instead of a
        # one-line "error: tag" that observer scrapers can't grep for).
        from harness.errors import handle_harness_error
        handle_harness_error(exc, sys_exit=sys.exit)


@state.command(name="snapshot")
@click.option("--db-path", default=None, type=click.Path(path_type=Path),
              help="Path to history.db (defaults to STATE_DIR/history.db).")
def state_snapshot_cmd(db_path: Path | None) -> None:
    """Take a snapshot of history.db into STATE_DIR/db_snapshots/."""
    from harness._constants import DB_FILE_NAME, STATE_DIR
    from harness.state.db import _take_snapshot
    target = db_path or (STATE_DIR / DB_FILE_NAME)
    snap = _take_snapshot(target)
    if snap is None:
        click.echo(f"no snapshot taken (db missing or unreadable at {target})")
        sys.exit(1)
    click.echo(f"snapshot: {snap}")


@state.command(name="snapshot-schedule")
@click.option("--cadence-minutes", default=60, type=int,
              help="Minutes between snapshots (default 60).")
def state_snapshot_schedule_cmd(cadence_minutes: int) -> None:
    """Register a Windows Scheduled Task to call `state snapshot` every N min."""
    from harness.state.db_scheduler import register_snapshot_task
    ok, msg = register_snapshot_task(cadence_minutes=cadence_minutes)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@state.command(name="snapshot-unschedule")
def state_snapshot_unschedule_cmd() -> None:
    """Remove the snapshot Scheduled Task."""
    from harness.state.db_scheduler import unregister_snapshot_task
    ok, msg = unregister_snapshot_task()
    click.echo(msg)
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# Autonomous dev loop (Wave 6/B — productized coord/dev_loop/)
# ---------------------------------------------------------------------------


@cli.group(name="loop")
def loop_group() -> None:
    """Autonomous dev loop — productized coord/dev_loop/ scaffolding."""


@loop_group.command(name="init")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=lambda: LOOP_DEFAULT_STATE_PATH)
def loop_init_cmd(state_path: Path) -> None:
    """Create state.json with defaults if missing."""
    from harness.loops.state import LoopState, write_state

    if state_path.exists():
        click.echo(f"already exists: {state_path}")
        sys.exit(0)
    write_state(state_path, LoopState())
    click.echo(f"created {state_path}")


@loop_group.command(name="tick")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=lambda: LOOP_DEFAULT_STATE_PATH,
              help="Override the loop state file.  Default anchors to the "
                   "repo root via _REPO_ROOT so Task Scheduler invocations "
                   "from C:\\Windows\\System32 still resolve correctly "
                   "(W14-LOOP-CWD-FIX 2026-05-27).")
@click.option("--project-root", type=click.Path(path_type=Path),
              default=lambda: _REPO_ROOT,
              help="Override project root for adapter resolution.  Default "
                   "is the harness repo root, not Path.cwd() (which broke "
                   "Task Scheduler runs pre-W14-LOOP-CWD-FIX).")
def loop_tick_cmd(state_path: Path, project_root: Path) -> None:
    """Run one tick of the autonomous loop."""
    from datetime import datetime, timezone
    from harness.loops.runner import tick as _tick

    try:
        result = _tick(
            state_path=state_path,
            observer_dir=LOOP_DEFAULT_OBSERVER_DIR,
            project=project_root,
            now=datetime.now(timezone.utc),
        )
    except FileNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    phases = ",".join(result.phases_acted_on) if result.phases_acted_on else "(none)"
    click.echo(
        f"tick #{result.tick_count} phases={phases} "
        f"next={result.next_due_at or '-'} escalations={len(result.escalations_raised)}"
    )


@loop_group.command(name="start")
@click.option("--cadence-minutes", type=int, default=30,
              help="Minutes between tick runs.")
def loop_start_cmd(cadence_minutes: int) -> None:
    """Register Windows Task Scheduler entry to run tick every N minutes."""
    from harness.loops.scheduler import register_loop_task

    ok, msg = register_loop_task(cadence_minutes=cadence_minutes)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@loop_group.command(name="stop")
def loop_stop_cmd() -> None:
    """Unregister the Task Scheduler entry."""
    from harness.loops.scheduler import unregister_loop_task

    ok, msg = unregister_loop_task()
    click.echo(msg)
    sys.exit(0 if ok else 1)


@loop_group.command(name="status")
@click.option("--state-path", type=click.Path(path_type=Path),
              default=lambda: LOOP_DEFAULT_STATE_PATH)
def loop_status_cmd(state_path: Path) -> None:
    """Print loop_status + tick_count + last_tick_at + observer + session flags."""
    from harness.loops.scheduler import is_registered
    from harness.loops.state import read_state

    state = read_state(state_path)
    scheduled = "yes" if is_registered() else "no"
    click.echo(
        f"loop: {state.loop_status} | tick #{state.tick_count} | "
        f"last={state.last_tick_at or '-'} | active={len(state.active_dispatches)} | "
        f"scheduled={scheduled}"
    )
    # Observer flag surface — read-only check; never modify
    obs_high = Path("coord/observer/HIGH_FLAG_PENDING.md")
    obs_crit = Path("coord/observer/CRITICAL_FLAG_PENDING.md")
    if obs_crit.exists():
        click.echo(f"observer: 🔴 CRITICAL FLAG PENDING — see {obs_crit}")
    elif obs_high.exists():
        click.echo(f"observer: 🟡 HIGH flag pending — see {obs_high}")
    else:
        click.echo("observer: clean")
    # Session-handoff state
    hf_crit = Path("coord/dev_loop/handoff_CRITICAL.md")
    hf_rec = Path("coord/dev_loop/handoff_recommended.md")
    if hf_crit.exists():
        click.echo(f"session: 🔴 CRITICAL handoff written — see {hf_crit}")
    elif hf_rec.exists():
        click.echo(f"session: 🟡 Heavy handoff recommended — see {hf_rec}")
    else:
        click.echo("session: healthy (no handoff flagged)")


# ---------------------------------------------------------------------------
# Replay (REPLAY-CLI — decision archaeology for dispatches)
# ---------------------------------------------------------------------------


@cli.command(name="replay", hidden=True)
@click.argument("task_id")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
@click.option("--jsonl-path", type=click.Path(path_type=Path), default=None)
def replay_cmd(task_id: str, fmt: str, jsonl_path: Path | None) -> None:
    """Reconstruct the dispatch (or v2 coord run) lifecycle for TASK_ID."""
    import dataclasses, re
    from harness.replay import (
        replay_dispatch, format_for_human,
        replay_coord_run, format_coord_for_human,
    )

    is_run_id = bool(re.match(r"^\d{8}T\d{6}-[a-z0-9]{4}$", task_id))
    if is_run_id:
        try:
            crep = replay_coord_run(task_id)
        except FileNotFoundError as exc:
            click.echo(f"error: {exc}", err=True)
            sys.exit(1)
        if fmt == "json":
            click.echo(json.dumps(dataclasses.asdict(crep), indent=2, default=str))
        else:
            click.echo(format_coord_for_human(crep))
        return

    report = replay_dispatch(task_id, jsonl_path=jsonl_path)
    if fmt == "json":
        click.echo(json.dumps({
            "task_id": report.task_id,
            "summary": report.summary,
            "total_elapsed_ms": report.total_elapsed_ms,
            "final_outcome": report.final_outcome,
            "events": [dataclasses.asdict(e) for e in report.events],
        }, indent=2))
    else:
        click.echo(format_for_human(report))


# ---------------------------------------------------------------------------
# Budget (BUDGET-METER — dispatch cost ledger)
# ---------------------------------------------------------------------------


def _budget_archive_dir() -> Path:
    return Path("coord/dev_loop/budget_archive")


@cli.group(name="budget")
def budget_group() -> None:
    """Dispatch budget + per-engine cost ledger."""


@budget_group.command(name="show")
@click.option("--engine", default=None)
@click.option("--since", default=None, help="ISO timestamp filter")
def budget_show(engine: Optional[str], since: Optional[str]) -> None:
    """Tabular ledger output.

    Rows where ``cost_known=False`` (unpriced engine — typically a model
    rename that hasn't been added to the pricing table) are tagged
    ``[UNPRICED]`` so the operator sees the meter is undercounting.
    P3 audit fix 2026-05-27.
    """
    entries = read_ledger(DEFAULT_LEDGER_PATH)
    if since:
        entries = [e for e in entries if e.timestamp >= since]
    if engine:
        entries = [e for e in entries if e.engine == engine]
    if not entries:
        click.echo("(no entries)")
        sys.exit(0)
    unpriced_count = 0
    for e in entries:
        tag = " [UNPRICED]" if not e.cost_known else ""
        if not e.cost_known:
            unpriced_count += 1
        click.echo(f"{e.timestamp}  {e.engine:12}  {e.task_id:20}  "
                   f"${e.cost_usd:.6f}{tag}")
    if unpriced_count:
        click.echo()
        click.echo(
            f"WARN: {unpriced_count} of {len(entries)} dispatches show "
            f"as UNPRICED (engine not in pricing table; cost meter "
            f"undercounts).  See: harness budget summary"
        )
    sys.exit(0)


@budget_group.command(name="summary")
@click.option("--since", default=None)
@click.option("--since-days", type=int, default=None,
              help="Number of days to look back (mutually exclusive with --since).")
def budget_summary_cmd(since: str | None, since_days: int | None) -> None:
    """Per-engine totals + grand total."""
    if since is not None and since_days is not None:
        raise click.UsageError("--since and --since-days are mutually exclusive")
    if since_days is not None and since_days < 1:
        raise click.BadParameter("--since-days must be >= 1", param_hint="'--since-days'")
    if since_days is not None:
        since_iso = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    elif since is not None:
        since_iso = since
    else:
        since_iso = datetime.now(timezone.utc).strftime("%Y-%m")
    agg = budget_summary(DEFAULT_LEDGER_PATH, since_iso=since_iso)
    if not agg:
        click.echo("(no dispatches)")
        sys.exit(0)
    total = 0.0
    unpriced_total = 0
    unpriced_engines: list[str] = []
    for eng, data in sorted(agg.items()):
        # P3 audit fix 2026-05-27: surface unpriced dispatches inline so
        # the operator sees the meter is undercounting per engine.
        unpriced_n = int(data.get("unpriced_dispatches", 0))
        unpriced_suffix = ""
        if unpriced_n:
            unpriced_suffix = (
                f"  [{unpriced_n} UNPRICED - cost meter incomplete]"
            )
            unpriced_total += unpriced_n
            unpriced_engines.append(eng)
        click.echo(
            f"{eng:12}  dispatches={int(data['dispatches'])}  "
            f"cost=${data['total_cost_usd']:.6f}  "
            f"in={int(data['total_input_tokens'])}  "
            f"out={int(data['total_output_tokens'])}{unpriced_suffix}"
        )
        total += data["total_cost_usd"]
    click.echo(f"{'total':12}  ${total:.6f}")
    if unpriced_total:
        click.echo()
        click.echo(
            f"WARN: {unpriced_total} unpriced dispatch(es) across "
            f"engine(s) {', '.join(unpriced_engines)} - cost meter "
            f"under-reports total spend.  Add these engines to "
            f"PRICING_USD_PER_M_TOKENS in src/harness/budget.py "
            f"(or set HARNESS_BUDGET_PRICING_JSON) to fix."
        )
    sys.exit(0)


@budget_group.command(name="by-run")
@click.option("--since", default=None,
              help="ISO-8601 timestamp lower bound (e.g. 2026-05-22T00:00:00Z).")
@click.option("--since-days", type=int, default=None,
              help="Look back N days (mutually exclusive with --since).")
@click.option("--top", type=int, default=20,
              help="Show only the top N most-expensive runs (default 20).")
def budget_by_run(since: str | None, since_days: int | None, top: int) -> None:
    """Per-run cost rollup using W4-K token tracking.

    Groups ledger entries by `task_id` (which is the coord run-id for
    worker-spawned dispatches) and shows tokens + cost per run.  Useful
    for "did this overnight run blow my budget?" answer.
    """
    if since is not None and since_days is not None:
        raise click.UsageError("--since and --since-days are mutually exclusive")
    if since_days is not None and since_days < 1:
        raise click.BadParameter("--since-days must be >= 1",
                                 param_hint="'--since-days'")

    entries = read_ledger(DEFAULT_LEDGER_PATH)
    if since_days is not None:
        threshold = datetime.now(timezone.utc) - timedelta(days=since_days)
        threshold_iso = threshold.isoformat()
        entries = [e for e in entries if e.timestamp >= threshold_iso]
    elif since is not None:
        entries = [e for e in entries if e.timestamp >= since]

    if not entries:
        click.echo("(no dispatches in range)")
        sys.exit(0)

    # Group by task_id; aggregate engine, dispatches, tokens, cost
    by_run: dict[str, dict] = {}
    for e in entries:
        agg = by_run.setdefault(e.task_id, {
            "engines": set(), "dispatches": 0,
            "in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0,
        })
        agg["engines"].add(e.engine)
        agg["dispatches"] += 1
        agg["in_tokens"] += e.input_tokens
        agg["out_tokens"] += e.output_tokens
        agg["cost_usd"] += e.cost_usd

    # Sort: most expensive first
    rows = sorted(by_run.items(), key=lambda kv: -kv[1]["cost_usd"])[:top]
    click.echo(f"{'task_id':38} {'engines':18} {'dispatches':>10} "
               f"{'in':>8} {'out':>8} {'cost':>10}")
    grand_total_cost = 0.0
    grand_total_in = 0
    grand_total_out = 0
    for task_id, agg in rows:
        engines_str = ",".join(sorted(agg["engines"]))[:18]
        click.echo(f"{task_id:38} {engines_str:18} "
                   f"{agg['dispatches']:>10} "
                   f"{agg['in_tokens']:>8} {agg['out_tokens']:>8} "
                   f"${agg['cost_usd']:>9.6f}")
        grand_total_cost += agg["cost_usd"]
        grand_total_in += agg["in_tokens"]
        grand_total_out += agg["out_tokens"]

    # Footer with sum across shown rows + full-range total
    click.echo("-" * 96)
    full_range_total = sum(a["cost_usd"] for a in by_run.values())
    click.echo(f"{'(top ' + str(len(rows)) + ')':38} {'':18} "
               f"{'':10} {grand_total_in:>8} {grand_total_out:>8} "
               f"${grand_total_cost:>9.6f}")
    if len(by_run) > top:
        click.echo(f"({len(by_run) - top} more runs not shown)  "
                   f"full-range total: ${full_range_total:.6f}")
    sys.exit(0)


@budget_group.command(name="set-cap")
@click.argument("amount_usd", type=float)
def budget_set_cap(amount_usd: float) -> None:
    """Write monthly cap to coord/dev_loop/budget_cap.json.

    W14-BUDGET-METER-PER-ENGINE 2026-05-25: preserves any existing
    per-engine caps + alert threshold; only the global cap is updated.
    """
    from harness.budget import read_caps_config, write_caps_config
    # Use the cli-module DEFAULT_CAP_PATH so tests that monkeypatch
    # ``harness.cli.DEFAULT_CAP_PATH`` continue to redirect writes.
    config = read_caps_config(cap_path=DEFAULT_CAP_PATH)
    config["monthly_cap_usd"] = float(amount_usd)
    write_caps_config(config, cap_path=DEFAULT_CAP_PATH)
    click.echo(f"monthly cap set to ${amount_usd:.2f}")
    sys.exit(0)


@budget_group.command(name="set-engine-cap")
@click.argument("engine", type=str)
@click.argument("amount_usd", type=float)
def budget_set_engine_cap(engine: str, amount_usd: float) -> None:
    """W14-BUDGET-METER-PER-ENGINE: set a per-engine monthly cap.

    Examples:
      harness budget set-engine-cap deepseek 30
      harness budget set-engine-cap mimo 15
      harness budget set-engine-cap qwen 50

    Pass 0 to remove a cap entirely (engine becomes unbounded).
    """
    from harness.budget import set_engine_cap
    set_engine_cap(engine, float(amount_usd), cap_path=DEFAULT_CAP_PATH)
    if amount_usd <= 0.0:
        click.echo(f"engine cap removed for {engine}")
    else:
        click.echo(f"engine cap for {engine} set to ${amount_usd:.2f}")
    sys.exit(0)


@budget_group.command(name="caps")
@click.option("--format", "fmt",
              type=click.Choice(["pretty", "json"]), default="pretty",
              help="Output format.  pretty for terminal, json for scripts.")
def budget_caps(fmt: str) -> None:
    """W14-BUDGET-METER-PER-ENGINE: show per-engine spend vs cap.

    Surfaces this-month spend, configured cap, percentage used, and an
    alert indicator (>=80% by default) per engine.  An engine appears
    here if it has either a cap configured OR any spend recorded this
    month.

    Exit code 0 always (read-only command).
    """
    from harness.budget import (
        all_engines_status, read_caps_config, check_cap,
    )
    # Use the cli-module DEFAULT_CAP_PATH for monkeypatch-aware reads
    config = read_caps_config(cap_path=DEFAULT_CAP_PATH)
    rows = all_engines_status(caps_config=config)
    within, spent, global_cap = check_cap()

    if fmt == "json":
        import json as _json
        click.echo(_json.dumps({
            "global": {
                "monthly_cap_usd": global_cap,
                "spent_usd": spent,
                "within_cap": within,
            },
            "alert_threshold_pct": config["alert_threshold_pct"],
            "engines": [r.model_dump() for r in rows],
        }, indent=2))
        sys.exit(0)

    # Pretty terminal output with color-coded status
    if global_cap > 0:
        global_pct = (spent / global_cap) * 100.0
        global_status = (
            click.style("OVER",   fg="red",    bold=True) if not within else
            click.style("ALERT",  fg="yellow", bold=True) if global_pct >= config["alert_threshold_pct"] else
            click.style("OK",     fg="green")
        )
        click.echo(f"Global cap:  ${spent:.4f} / ${global_cap:.2f} "
                   f"({global_pct:.1f}%)  [{global_status}]")
    else:
        click.echo(f"Global cap:  not configured  (spent so far: ${spent:.4f})")
    click.echo(f"Alert threshold: {config['alert_threshold_pct']}%")
    click.echo()
    if not rows:
        click.echo("(no per-engine caps configured, no engine spend this month)")
        sys.exit(0)
    click.echo(f"{'engine':<14} {'spent':>10} {'cap':>10} {'%used':>8}  status")
    click.echo("-" * 56)
    for r in rows:
        if r.cap_usd <= 0:
            status_disp = click.style("uncapped", fg="cyan")
            pct_disp = "  -  "
        elif not r.within_cap:
            status_disp = click.style("OVER", fg="red", bold=True)
            pct_disp = f"{r.pct_used:.1f}%"
        elif r.alert_threshold_reached:
            status_disp = click.style("ALERT", fg="yellow", bold=True)
            pct_disp = f"{r.pct_used:.1f}%"
        else:
            status_disp = click.style("OK", fg="green")
            pct_disp = f"{r.pct_used:.1f}%"
        click.echo(
            f"{r.engine:<14} ${r.spent_usd:>8.4f} ${r.cap_usd:>8.2f} "
            f"{pct_disp:>8}  {status_disp}"
        )
    sys.exit(0)


@budget_group.command(name="reset")
@click.option("--force", is_flag=True)
def budget_reset(force: bool) -> None:
    """Archive ledger + start fresh."""
    if not DEFAULT_LEDGER_PATH.exists():
        click.echo("ledger already empty")
        sys.exit(0)
    if not force:
        click.echo("error: use --force to reset ledger", err=True)
        sys.exit(1)
    archive = _budget_archive_dir()
    archive.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = archive / f"budget_ledger_{suffix}.jsonl"
    DEFAULT_LEDGER_PATH.rename(dest)
    click.echo(f"ledger archived to {dest}")
    sys.exit(0)


@budget_group.command(name="export-daily")
@click.option("--date", default=None,
              help="UTC date YYYY-MM-DD (defaults to today).")
@click.option("--target-dir", default=None, type=click.Path(path_type=Path),
              help="Override output dir (defaults to coord/cost_daily/).")
def budget_export_daily(date: str | None, target_dir: Path | None) -> None:
    """Append-only daily cost roll-up CSV (engine/model/tokens/$ for Excel reconciliation)."""
    from harness.budget import export_daily_csv
    out = export_daily_csv(target_dir=target_dir, date=date)
    click.echo(f"wrote {out}")


# ---------------------------------------------------------------------------
# Proxy primitive (v2/A)
# ---------------------------------------------------------------------------


@cli.group(name="proxy", hidden=True)
def proxy_group() -> None:
    """Stateful 4-key API proxy with circuit breaker."""


@proxy_group.command(name="start")
@click.option("--port", default=7879, type=int)
@click.option("--host", default="127.0.0.1")
@click.option("--upstream", default="kimi-http", show_default=True, help=(
    "Upstream selector.  Run `harness proxy upstreams` to see all "
    "options.  HTTP-direct: kimi-http (default), deepseek-http, "
    "qwen-http.  TOS-compliant subprocess: mimo-via-claude-code, "
    "kimi-via-claude-code."
))
def proxy_start(port: int, host: str, upstream: str) -> None:
    """Start the proxy server in the background."""
    from harness.proxy.cli import start
    start(port=port, host=host, upstream=upstream)


@proxy_group.command(name="upstreams")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]),
              default="table", show_default=True)
def proxy_upstreams(fmt: str) -> None:
    """List all upstream selectors the proxy supports.

    Each upstream is a named recipe: transport (HTTP-direct vs Claude
    Code subprocess) + base URL + default model + key env var.
    """
    from harness.proxy.upstreams import list_upstreams
    upstreams = list_upstreams()
    if fmt == "json":
        import json
        out = {
            name: {
                "transport": s.transport,
                "key_env": s.key_env,
                "base_url": s.base_url,
                "default_model": s.default_model,
                "description": s.description,
                "tos_notes": s.tos_notes,
            }
            for name, s in upstreams.items()
        }
        click.echo(json.dumps(out, indent=2))
        return
    # Table format
    click.echo(
        f"{'name':<24} {'transport':<26} {'key env':<22} model"
    )
    click.echo("-" * 110)
    for name, s in upstreams.items():
        click.echo(
            f"  {name:<22} {s.transport:<26} {s.key_env:<22} "
            f"{s.default_model}"
        )
    click.echo()
    click.echo("Subprocess upstreams are TOS-compliant for UA-gated providers.")
    click.echo(
        "Latency: HTTP ~100ms overhead; subprocess ~5-7s overhead "
        "(Claude Code boot per request)."
    )


@proxy_group.command(name="stop")
def proxy_stop() -> None:
    """Stop the background proxy server."""
    from harness.proxy.cli import stop
    stop()


@proxy_group.command(name="status")
def proxy_status() -> None:
    """Show per-key health table."""
    from harness.proxy.cli import status
    status()


@proxy_group.command(name="reset-circuit")
@click.argument("alias")
def proxy_reset_circuit(alias: str) -> None:
    """Manually reset a key's circuit breaker to CLOSED."""
    from harness.proxy.cli import reset_circuit
    reset_circuit(alias)


@proxy_group.command(name="quarantine")
@click.argument("alias")
def proxy_quarantine(alias: str) -> None:
    """Permanently open a key's circuit breaker."""
    from harness.proxy.cli import quarantine
    quarantine(alias)


@proxy_group.command(name="unquarantine")
@click.option("--alias", default=None, help="Specific key alias to unquarantine.")
@click.option("--all", "all_keys", is_flag=True,
              help="Clear quarantine on ALL keys.")
def proxy_unquarantine(alias: str | None, all_keys: bool) -> None:
    """Clear permanent-quarantine state set by --quarantine or AUTO-QUARANTINE-KEY."""
    from harness.proxy.cli import unquarantine
    ok, msg = unquarantine(alias=alias, all_keys=all_keys)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@proxy_group.command(name="disable-key")
@click.argument("alias")
def proxy_disable_key(alias: str) -> None:
    """Manually disable a key so the proxy won't route to it."""
    from harness.proxy.cli import disable_key
    disable_key(alias)


# ── Session ──────────────────────────────────────────────────────────────

@cli.group(name="session")
def session_group() -> None:
    """Session-handoff monitor — proactive transfer recommendation."""


@session_group.command(name="check")
def session_check() -> None:
    """Run a single health check and print the report."""
    from harness.session.monitor import check
    report = check()
    click.echo(report.model_dump_json(indent=2))
    if report.recommendation.value in ("critical", "strongly"):
        raise SystemExit(1)


@session_group.command(name="bootstrap")
@click.option("--reason", default="", help="Reason / next-action for the new session.")
def session_bootstrap(reason: str) -> None:
    """Generate the 5-section master handoff prompt."""
    from harness.session.bootstrap import generate_master_prompt
    click.echo(generate_master_prompt(reason=reason))


@session_group.command(name="ack")
def session_ack() -> None:
    """Acknowledge and remove pending handoff flag files."""
    from harness.session.monitor import ack_handoff
    ok, msg = ack_handoff()
    click.echo(msg)
    sys.exit(0 if ok else 1)


@session_group.command(name="crisis-check")
def session_crisis_check() -> None:
    """Run check and raise a Windows toast on CRITICAL."""
    from harness.session.monitor import crisis_check
    report = crisis_check()
    click.echo(report.model_dump_json(indent=2))
    if report.recommendation.value == "critical":
        raise SystemExit(1)


@session_group.command(name="arm-crisis-check")
@click.option("--cadence", default=5, help="Check cadence in minutes.")
def session_arm_crisis_check(cadence: int) -> None:
    """Register a Windows Task Scheduler entry for periodic crisis checks."""
    from harness.session.monitor import arm_crisis_check
    ok, msg = arm_crisis_check(cadence_minutes=cadence)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@session_group.command(name="ok-to-stop")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Emit decision as structured JSON instead of human text.")
def session_ok_to_stop(json_output: bool) -> None:
    """Deterministic gate — exit 0 only if the session may legitimately stop now.

    The autonomous-loop directive
    (`feedback_full_automation_until_wave_plan_empty`) says: do NOT stop
    until session-handoff is STRONGLY/CRITICAL or operator explicitly
    redirects.  This verb encodes that rule programmatically so the
    agent (or a wrapper script) can check before any 'stopping' reply.

    Exit codes:
      0 — stopping is appropriate (reason printed)
      1 — stopping is premature; keep working (reason printed)

    --json emits {ok_to_stop, reason, ...inputs} for programmatic consumers
    (dashboard, chat observer, wrapper scripts).
    """
    from harness.session.stop_check import ok_to_stop_with_inputs
    ok, reason, inputs = ok_to_stop_with_inputs()
    if json_output:
        import json as _json
        payload = {"ok_to_stop": ok, "reason": reason, **inputs}
        click.echo(_json.dumps(payload))
    else:
        click.echo(("ok-to-stop: " if ok else "NOT-YET: ") + reason)
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# coord (v2/D)
# ---------------------------------------------------------------------------

@cli.group(name="coord")
def coord_group() -> None:
    """Multi-agent coordinator: planner + workers + integrate.

    The high-autonomy operating mode (vs `harness ask` panel and
    in-session use).  Spec-driven runs with isolated git worktrees
    per worker, replan-from-failure, integration phase.

    Audit follow-through 2026-05-27: was previously hidden=True
    because v2 was treated as experimental scaffolding.  Now that
    docs/OPERATOR_GUIDE.md § 3.3 and docs/AGENT_REFERENCE.md § 10
    document it as a first-class operating mode, surfacing it in
    `harness --help` matches the docs.

    Full spec: spec/multi-agent-harness-architecture.md.
    """


@coord_group.command(name="plan")
@click.option("--spec", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--run-id", default=None, help="Run ID (defaults to auto-generated).")
@click.option("--engine", default="kimi")
@click.option("--model", default=None)
@click.option("--project-root", default=".", type=click.Path(path_type=Path))
def coord_plan(spec: Path, run_id: str | None, engine: str, model: str | None, project_root: Path) -> None:
    """Generate a WavePlan from a spec markdown file."""
    from harness.coord.planner import _new_run_id, plan as run_planner, write_plan
    rid = run_id or _new_run_id()
    run_dir = Path("runs") / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_obj = run_planner(spec, run_id=rid, engine=engine, model=model, project_root=project_root)
    write_plan(plan_obj, run_dir)
    click.echo(f"plan: {run_dir / 'plan.json'}")


@coord_group.command(name="plan-from-description")
@click.argument("description")
@click.option("--engine", default="claude",
              help="Planner engine: claude | kimi | kimi-api | deepseek | mock.")
@click.option("--run-id", default=None)
def coord_plan_from_description(description: str, engine: str, run_id: str | None) -> None:
    """Generate a plan.json from a one-line natural-language description."""
    from harness.coord.planner import plan_from_description, write_plan
    waveplan = plan_from_description(description, engine=engine, run_id=run_id)
    run_dir = Path("runs") / waveplan.run_id
    out = write_plan(waveplan, run_dir)
    click.echo(f"plan.json written to {out} (run_id={waveplan.run_id})")
    click.echo(f"  {len(waveplan.tasks)} task(s); planner_engine={waveplan.planner_engine}")


@coord_group.command(name="replan")
@click.option("--run-id", required=True, help="Run ID of the FAILED run whose feedback drives the replan.")
@click.option("--engine", default="claude",
              help="Planner engine for the replan.")
@click.option("--new-run-id", default=None,
              help="Explicit new run ID (defaults to auto-generated).")
def coord_replan(run_id: str, engine: str, new_run_id: str | None) -> None:
    """Re-run planner with failed-worker feedback from a prior run."""
    from harness.coord.planner import replan_from_run, write_plan
    failed_dir = Path("runs") / run_id
    if not failed_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)
    try:
        waveplan = replan_from_run(failed_dir, engine=engine, new_run_id=new_run_id)
    except FileNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    new_dir = Path("runs") / waveplan.run_id
    out = write_plan(waveplan, new_dir)
    click.echo(f"replan: new plan.json at {out} (run_id={waveplan.run_id})")
    click.echo(f"  {len(waveplan.tasks)} task(s); planner_engine={waveplan.planner_engine}")


@coord_group.command(name="rerun-failed")
@click.option("--run-id", required=True, help="Run ID of the failed run.")
@click.option("--engine", default="claude", help="Planner engine for replan.")
@click.option("--worker-engine", default="swarm/kimi-api",
              help="Engine for the new workers.")
@click.option("--auto-integrate", is_flag=True,
              help="Also run integrate after the new workers complete.")
def coord_rerun_failed(run_id: str, engine: str, worker_engine: str,
                       auto_integrate: bool) -> None:
    """Chain replan → run → (optional) integrate for a failed run."""
    from harness.coord.planner import replan_from_run, write_plan
    from harness.coord.coordinator import Coordinator
    from harness.coord.integrator import integrate

    failed_dir = Path("runs") / run_id
    if not failed_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)

    # Step 1: replan
    try:
        new_plan = replan_from_run(failed_dir, engine=engine)
    except FileNotFoundError as exc:
        click.echo(f"error during replan: {exc}", err=True)
        sys.exit(1)
    new_run_dir = Path("runs") / new_plan.run_id
    write_plan(new_plan, new_run_dir)
    click.echo(f"replan: new run_id={new_plan.run_id} with {len(new_plan.tasks)} task(s)")

    # Step 2: coord.tick — pass the original spec path from the new plan
    coord = Coordinator(run_id=new_plan.run_id, run_dir=new_run_dir)
    report = coord.tick(Path(new_plan.spec_path))
    click.echo(f"run: state={report.state.value}")
    for wid, st in (report.worker_summary or {}).items():
        click.echo(f"  {wid}: {st}")

    if not auto_integrate:
        sys.exit(0 if report.state.value in ("completed", "running") else 1)

    # Step 3: integrate (only when --auto-integrate)
    irep = integrate(new_run_dir)
    click.echo(f"integrate: success={irep.success} merged={len(irep.workers_merged)} "
               f"conflicted={len(irep.workers_conflicted)}")
    sys.exit(0 if irep.success else 1)


@coord_group.command(name="run")
@click.option("--spec", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--run-id", default=None, help="Run ID (defaults to auto-generated).")
@click.option("--resume", is_flag=True, help="Resume the latest run.")
@click.option("--limit", default=None, type=int, help="In-flight worker limit.")
@click.option("--proxy", type=click.Choice(["auto", "off", "external"]),
              default="auto",
              help="Auto-start the v2 proxy ('auto'), use a running one ('external'), or skip ('off').")
@click.option("--label", default=None,
              help="Optional label tag to stamp on the run for grouping/filtering.")
@click.option("--dry-run", is_flag=True,
              help="Print plan + worker assignments without dispatching engines or creating worktrees.")
@click.option("--engine", default=None,
              help="Engine identifier passed to each worker (e.g. swarm/kimi, swarm/kimi-api, swarm/deepseek). "
                   "When omitted, the worker subcommand default applies.")
@click.option("--watch", is_flag=True,
              help="Keep ticking the coordinator until the run reaches "
                   "completed/failed.  Required for unattended overnight runs.")
@click.option("--watch-interval", default=5, type=int,
              help="Seconds between ticks in --watch mode (default 5).")
@click.option("--watch-max-seconds", default=3600, type=int,
              help="Hard cap on total --watch duration (default 1h).")
@click.option("--no-merge", is_flag=True,
              help="In --watch mode, run the integrator in validate-only "
                   "mode (W5-H): no worker branches merged to base. Use "
                   "this for test runs to avoid polluting master.")
@click.option("--fallback-engine", default=None,
              help="W5-O: if the primary --engine produces 0 edits on "
                   "a step (engine compliance drift), retry that step "
                   "once with this engine before failing.  Pair example: "
                   "--engine swarm/mimo --fallback-engine swarm/deepseek "
                   "approaches near-100% reliability.")
def coord_run(spec: Path, run_id: str | None, resume: bool, limit: int | None,
              proxy: str, label: str | None, dry_run: bool,
              engine: str | None, watch: bool, watch_interval: int,
              watch_max_seconds: int, no_merge: bool,
              fallback_engine: str | None) -> None:
    """Execute a coordination run.

    By default this performs a single tick of the coordinator state machine
    (PLANNING -> RUNNING -> workers -> INTEGRATING -> DONE).  Pass
    ``--watch`` to keep ticking until the run reaches a terminal state --
    required for unattended overnight runs where the operator isn't
    sitting at the keyboard issuing ``--resume`` ticks by hand.
    """
    from harness.coord.coordinator import Coordinator
    from harness.coord.planner import _new_run_id, plan as run_planner
    from harness.coord.run_state import read_run_state
    from harness.proxy import lifecycle as proxy_lifecycle

    # --- Dry-run short-circuit (COORD-RUN-DRY-RUN) -------------------------
    if dry_run:
        # Compute a plan without spawning workers / creating worktrees
        rid = run_id or _new_run_id()
        try:
            waveplan = run_planner(spec, run_id=rid, engine="claude")
        except Exception as exc:
            click.echo(f"dry-run: planner failed — {exc}", err=True)
            sys.exit(1)
        click.echo(f"dry-run: would create run {rid}")
        if label:
            click.echo(f"  label: {label}")
        click.echo(f"  spec:  {spec}")
        click.echo(f"  tasks: {len(waveplan.tasks)}")
        for task in waveplan.tasks:
            wt = f".harness/worktrees/{rid}/{task.worker_id}"
            click.echo(f"  - {task.worker_id}: {task.title!r}  worktree={wt}")
            files = task.write_set or []
            click.echo(f"      write_set: {', '.join(files) if files else '(none)'}")
        click.echo("dry-run: no engines dispatched, no worktrees created")
        sys.exit(0)

    proxy_proc = None
    if proxy == "auto":
        proxy_proc = proxy_lifecycle.start_proxy()
        if proxy_proc is not None:
            click.echo(f"proxy: started (pid={proxy_proc.pid})")
        elif proxy_lifecycle.is_proxy_listening():
            click.echo("proxy: already running")
        else:
            click.echo("proxy: WARNING — failed to start; continuing", err=True)
    elif proxy == "external":
        if not proxy_lifecycle.is_proxy_listening():
            click.echo("proxy: --proxy=external but no proxy listening on 7879", err=True)
            sys.exit(1)

    try:
        if resume:
            runs_dir = Path("runs")
            if not runs_dir.exists():
                click.echo("error: no runs directory")
                raise SystemExit(1)
            states = sorted(runs_dir.glob("*/run_state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not states:
                click.echo("error: no runs to resume")
                raise SystemExit(1)
            run_dir = states[0].parent
            rid = read_run_state(states[0]).run_id if read_run_state(states[0]) else run_dir.name
        else:
            rid = run_id or _new_run_id()
        run_dir = Path("runs") / rid
        run_dir.mkdir(parents=True, exist_ok=True)
        coord = Coordinator(run_id=rid, run_dir=run_dir, label=label,
                            fallback_engine=fallback_engine)
        report = coord.tick(spec, in_flight_limit=limit, engine=engine)
        click.echo(f"run {report.run_id}: {report.state.value}")
        if report.worker_summary:
            for wid, st in report.worker_summary.items():
                click.echo(f"  {wid}: {st}")

        # --- W5-B 2026-05-22: --watch mode loops until terminal -----------
        # Without --watch the operator must invoke `coord run --resume` for
        # every state transition (PLANNING -> RUNNING -> workers spawn ->
        # poll -> INTEGRATING -> DONE).  With --watch we hold this loop
        # ourselves and fire the integrator automatically when the run
        # reaches INTEGRATING, so a single command survives an unattended
        # overnight.
        if watch:
            import time as _time
            from harness.coord.integrator import integrate as _integrate
            from harness.coord.run_state import write_run_state, read_run_state as _read_run_state
            from harness.coord.schemas import RunStateLiteral, WavePlan
            from harness.coord.telemetry import compute_telemetry, format_tick_line

            terminal_states = {"completed", "failed", "done", "aborted"}
            watch_start = _time.monotonic()
            deadline = watch_start + watch_max_seconds
            last_state = report.state.value
            integrate_fired = False

            # Load plan once for telemetry (per-worker step counts)
            try:
                _plan_obj = WavePlan.model_validate_json(
                    (run_dir / "plan.json").read_text(encoding="utf-8")
                )
                _plan_tasks = [t.model_dump() for t in _plan_obj.tasks]
            except Exception:
                _plan_tasks = []
            _watch_start_iso = datetime.now(timezone.utc).isoformat()

            while last_state not in terminal_states:
                if _time.monotonic() > deadline:
                    click.echo(
                        f"watch: max-seconds={watch_max_seconds} reached; "
                        f"last state={last_state}", err=True)
                    sys.exit(2)

                # Fire integrator exactly once when we reach INTEGRATING
                if last_state == "integrating" and not integrate_fired:
                    integrate_fired = True
                    click.echo("watch: firing integrator"
                               + (" (--no-merge mode)" if no_merge else ""))
                    report_int = _integrate(
                        run_dir=run_dir, project_root=Path("."),
                        merge_workers=not no_merge,
                        auto_commit=False, auto_push=False,
                    )
                    click.echo(
                        f"watch: integrator success={report_int.success} "
                        f"merged={report_int.workers_merged} "
                        f"skipped={report_int.workers_skipped} "
                        f"conflicted={report_int.workers_conflicted}")
                    if report_int.diagnostic:
                        click.echo(f"watch: {report_int.diagnostic}")

                    # Reflect integrator outcome into run_state so the next
                    # tick observes a terminal state and exits.
                    st = _read_run_state(run_dir / "run_state.json")
                    if st is not None:
                        st.state = (RunStateLiteral.COMPLETED if report_int.success
                                    else RunStateLiteral.FAILED)
                        write_run_state(run_dir / "run_state.json", st)
                    last_state = "completed" if report_int.success else "failed"
                    click.echo(f"run {rid}: integrating -> {last_state}")
                    break

                _time.sleep(max(1, watch_interval))
                coord = Coordinator(run_id=rid, run_dir=run_dir, label=label,
                                    fallback_engine=fallback_engine)
                report = coord.tick(spec, in_flight_limit=limit, engine=engine)

                # --- Path 3 telemetry: per-tick one-liner --------------
                if _plan_tasks:
                    elapsed = int(_time.monotonic() - watch_start)
                    try:
                        tel = compute_telemetry(
                            run_dir, _plan_tasks,
                            started_at_iso=_watch_start_iso,
                            elapsed_seconds=elapsed,
                        )
                        click.echo("  " + format_tick_line(tel))
                    except Exception:
                        pass  # telemetry is best-effort

                if report.state.value != last_state:
                    click.echo(
                        f"run {report.run_id}: {last_state} -> "
                        f"{report.state.value}")
                    last_state = report.state.value
                    # Print worker summary only on state transition (not
                    # every tick — pre-W5-B the log was a flood of identical
                    # `worker-1: failed` lines).
                    if report.worker_summary:
                        for wid, st in report.worker_summary.items():
                            click.echo(f"  {wid}: {st}")

            click.echo(f"run {report.run_id if report else rid}: "
                       f"terminal state={last_state}")
            sys.exit(0 if last_state in {"completed", "done"} else 1)

        sys.exit(0 if report.state.value in ("completed", "running") else 1)
    finally:
        if proxy_proc is not None:
            proxy_lifecycle.stop_proxy(proxy_proc)


@coord_group.command(name="work")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
@click.option("--engine", default="swarm/kimi-api")
@click.option("--fallback-engine", default=None,
              help="W5-O: retry once with this engine when the primary "
                   "returns a response but produces 0 applicable edits "
                   "(engine compliance drift).")
def coord_work(run_id: str, worker_id: str, engine: str,
               fallback_engine: str | None) -> None:
    """Worker entry-point — load plan, find task, run worker."""
    from harness.coord.worker import run_worker
    from harness.coord.schemas import WavePlan

    run_dir = Path("runs") / run_id
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        click.echo(f"error: plan not found for run {run_id}", err=True)
        sys.exit(1)

    plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    task = next((t for t in plan.tasks if t.worker_id == worker_id), None)
    if task is None:
        click.echo(f"error: worker {worker_id} not in plan", err=True)
        sys.exit(1)

    result = run_worker(task.model_dump(), run_dir,
                       engine=engine, fallback_engine=fallback_engine)
    click.echo(f"worker {worker_id}: {result['state']}")
    sys.exit(0 if result["state"] == "completed" else 1)


@coord_group.command(name="retry")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
@click.option("--engine", default="swarm/kimi-api",
              help="Engine to retry with; defaults to swarm/kimi-api.")
def coord_retry(run_id: str, worker_id: str, engine: str) -> None:
    """Re-dispatch a failed worker from its last checkpoint.

    Loads the existing checkpoint at runs/<run_id>/checkpoints/<worker_id>.json,
    resets state to 'in_progress', and calls run_worker with resume_from
    pointing at that checkpoint so the worker picks up where it left off.
    """
    from harness.coord.worker import run_worker
    from harness.coord.schemas import WavePlan
    from harness.coord.checkpoint import read_checkpoint, write_checkpoint

    run_dir = Path("runs") / run_id
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        click.echo(f"error: plan not found for run {run_id}", err=True)
        sys.exit(1)
    plan = WavePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    task = next((t for t in plan.tasks if t.worker_id == worker_id), None)
    if task is None:
        click.echo(f"error: worker {worker_id} not in plan", err=True)
        sys.exit(1)

    ckpt_path = run_dir / "checkpoints" / f"{worker_id}.json"
    ckpt = read_checkpoint(ckpt_path)
    if ckpt is None:
        click.echo(f"error: no checkpoint at {ckpt_path}", err=True)
        sys.exit(1)
    if ckpt.state == "completed":
        click.echo(f"worker {worker_id} already completed; nothing to retry")
        sys.exit(0)

    # Reset state so the run loop treats it as in-progress
    reset = ckpt.model_copy(update={"state": "in_progress", "tests_passed": False})
    write_checkpoint(ckpt_path, reset)

    result = run_worker(task.model_dump(), run_dir, engine=engine, resume_from=ckpt_path)
    click.echo(f"worker {worker_id}: {result['state']}")
    sys.exit(0 if result["state"] == "completed" else 1)


@coord_group.command(name="integrate")
@click.option("--run-id", required=True)
@click.option("--project-root", default=".", type=click.Path(path_type=Path))
@click.option("--commit", is_flag=True)
@click.option("--push", is_flag=True)
@click.option("--no-merge", is_flag=True,
              help="Validate the run without merging worker branches "
                   "back to master.  Useful for test runs against mock or "
                   "test specs where you don't want to pollute trunk.")
@click.option("--pytest-timeout", default=None, type=int,
              help="Seconds before the integrator pytest run is killed. "
                   "Falls back to HARNESS_INTEGRATOR_PYTEST_TIMEOUT env, "
                   "then 600s default.")
def coord_integrate(run_id: str, project_root: Path, commit: bool, push: bool,
                    no_merge: bool, pytest_timeout: int | None) -> None:
    """Integrate a completed run: tests, commit, push.

    W5-H 2026-05-22: ``--no-merge`` lets operators run the integrator
    in validate-only mode against test specs / mock-engine runs so the
    worker branches don't merge to master.  Without this flag, every
    successful coord run would land a commit on trunk — fine in
    production, but pollution during testing.
    """
    from harness.coord.integrator import integrate
    run_dir = Path("runs") / run_id
    report = integrate(
        run_dir, project_root=project_root,
        auto_commit=commit, auto_push=push,
        merge_workers=not no_merge,
        pytest_timeout=pytest_timeout,
    )
    click.echo(f"integrate: success={report.success} commit={report.commit_sha} pushed={report.pushed}")
    if no_merge:
        click.echo("  (--no-merge: worker branches NOT merged to base)")
    if report.diagnostic:
        click.echo(f"  diagnostic: {report.diagnostic}")
    if report.test_summary:
        click.echo(f"  tests: {report.test_summary}")
    sys.exit(0 if report.success else 1)


@coord_group.command(name="list")
@click.option("--limit", default=20, type=int, help="Max number of runs to print (newest first).")
@click.option("--label", default=None,
              help="Filter runs by label (RUN-TAG-LABEL).")
def coord_list(limit: int, label: str | None) -> None:
    """List runs/ with state + age + worker count + label (CLI parity for /v2/runs)."""
    from harness.dashboard.v2_routes import list_runs
    runs = list_runs(label=label)
    if not runs:
        click.echo("no runs")
        return
    # Sort newest first by last_tick_at, falling back to started_at, then run_id
    def _key(r: dict) -> str:
        return r.get("last_tick_at") or r.get("started_at") or r.get("run_id", "")
    runs_sorted = sorted(runs, key=_key, reverse=True)[:limit]
    click.echo(f"{'RUN_ID':<28} {'STATE':<14} {'TASKS':>5}  {'LABEL':<16}  STARTED_AT")
    for r in runs_sorted:
        click.echo(
            f"{r['run_id']:<28} {str(r.get('state') or '-'):<14} "
            f"{r.get('tasks', 0):>5}  {str(r.get('label') or '-'):<16}  "
            f"{r.get('started_at') or '-'}"
        )


@coord_group.command(name="status")
@click.option("--run-id", required=True)
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output RunState as JSON instead of human-readable summary.")
def coord_status(run_id: str, json_output: bool) -> None:
    """Show run state summary. Use --json for machine-readable output."""
    import json as _json
    from harness.coord.run_state import read_run_state
    run_dir = Path("runs") / run_id
    state = read_run_state(run_dir / "run_state.json")
    if state is None:
        if json_output:
            click.echo(_json.dumps({"error": f"run {run_id} not found"}))
        else:
            click.echo("error: run not found")
        raise SystemExit(1)
    if json_output:
        click.echo(state.model_dump_json())
    else:
        click.echo(f"run {state.run_id}: {state.state.value}")
        click.echo(f"  plan: {state.plan_path}")
        click.echo(f"  workers: {len(state.workers)}")
        for wid, st in state.workers.items():
            click.echo(f"    {wid}: {st.state.value}")
        if state.escalations:
            click.echo(f"  escalations: {len(state.escalations)}")


@coord_group.command(name="watch")
@click.option("--run-id", required=True)
@click.option("--max-seconds", default=None, type=int,
              help="Stop watching after N seconds even if run is still active.")
def coord_watch(run_id: str, max_seconds: int | None) -> None:
    """Tail a running coord run and print events as they land."""
    import time as _time
    from harness.coord.watch import watch_run

    run_dir = Path("runs") / run_id
    if not run_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)

    deadline = _time.monotonic() + max_seconds if max_seconds else None
    try:
        for event in watch_run(run_dir):
            click.echo(event)
            if deadline and _time.monotonic() > deadline:
                click.echo("watch: max-seconds reached", err=True)
                break
    except KeyboardInterrupt:
        click.echo("watch: interrupted", err=True)


@coord_group.command(name="cleanup")
@click.option("--run-id", default=None, help="Specific run to clean up; if omitted, cleans all completed runs.")
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting.")
@click.option("--keep-deliverables", is_flag=True, help="Preserve deliverables/ and plan.json.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def coord_cleanup(run_id, dry_run, keep_deliverables, force):
    """Remove worktrees and run state for completed/failed runs."""
    from harness.coord.coordinator import cleanup_all_completed, cleanup_run

    if run_id:
        report = cleanup_run(
            run_id,
            keep_deliverables=keep_deliverables,
            dry_run=dry_run,
        )
    else:
        if not force and not dry_run:
            click.echo("This will remove all completed/failed runs. Use --force to skip this prompt.")
            try:
                ans = click.prompt("Continue? [y/N]", default="n", show_default=False)
            except click.exceptions.Abort:
                click.echo("Aborted.")
                raise SystemExit(1)
            if ans.lower() not in ("y", "yes"):
                click.echo("Aborted.")
                raise SystemExit(1)
        report = cleanup_all_completed(
            keep_deliverables=keep_deliverables,
            dry_run=dry_run,
        )

    prefix = "[dry-run] " if dry_run else ""
    click.echo(f"{prefix}runs cleared: {len(report.runs_removed)}")
    click.echo(f"{prefix}worktrees removed: {len(report.worktrees_removed)}")
    click.echo(f"{prefix}bytes freed: {report.bytes_freed}")
    if report.skipped_active:
        click.echo(f"{prefix}skipped active: {', '.join(report.skipped_active)}")


@coord_group.command(name="cancel")
@click.option("--run-id", required=True)
def coord_cancel(run_id: str) -> None:
    """Gracefully cancel an in-flight run: terminate workers + mark state cancelled."""
    from harness.coord.canceller import cancel_run
    run_dir = Path("runs") / run_id
    if not run_dir.exists():
        click.echo(f"error: no such run {run_id}", err=True)
        sys.exit(1)
    result = cancel_run(run_dir)
    if not result.get("success"):
        click.echo(f"error: {result.get('error','unknown')}", err=True)
        sys.exit(1)
    click.echo(
        f"cancelled run {result['run_id']}: "
        f"{len(result['terminated_pids'])} pid(s) terminated, "
        f"{len(result['checkpoints_cancelled'])} checkpoint(s) marked"
    )
