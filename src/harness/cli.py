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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import click
import yaml

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


def main(*args, **kwargs):
    """Entry point that wraps click with W5-DD top-level HarnessError handler.

    Any ``HarnessError`` that escapes the click verb is routed through
    ``handle_harness_error`` so the operator sees the L5 escalation banner
    (or the L3/L4 one-line summary) instead of click's vanilla traceback.
    Exits with the level-derived exit code (0/0/1/3/4).

    Programmatic callers that catch HarnessError themselves can still call
    ``cli`` directly to bypass this.
    """
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


@cli.command(name="spec-register")
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


@cli.command(name="spec-verify")
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
def start_cmd(orchestrator: str | None, mode: str | None,
              just_list: bool, interval_minutes: int) -> None:
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


@cli.command(name="spec-init")
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
def status_list(filter_status: Optional[str], category: Optional[str], fmt: str) -> None:
    """List rows (with optional filters)."""
    from harness.status import read_status

    rows = read_status(_status_csv_path())
    if filter_status:
        rows = [r for r in rows if r.status.value == filter_status]
    if category:
        rows = [r for r in rows if r.category == category]
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
def adapter_validate(project: str) -> None:
    """Validate a project's harness-adapter.yaml."""
    try:
        load_project_adapter(project)
    except Exception as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"adapter for '{project}' is valid")
    sys.exit(0)


@cli.command(name="dashboard-serve")
@click.option("--port", default=7878, type=int, help="Dashboard server port.")
@click.option("--host", default="127.0.0.1", help="Dashboard server bind address.")
def dashboard_serve(port: int, host: str) -> None:
    """Run the operator-facing dashboard."""
    from harness.dashboard.server import serve

    serve(host=host, port=port)


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


@cli.command(name="lint-spec")
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
def doctor_cmd(fmt: str) -> None:
    """Preflight: check git, python, DPAPI, secrets, coord/ perms, Task Scheduler."""
    import dataclasses
    from harness.doctor import run_all, overall_severity

    diagnoses = run_all()
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


@cli.command(name="panic-dump")
@click.option("--target-dir", default=None, type=click.Path(path_type=Path),
              help="Output dir (defaults to cwd).")
def panic_dump_cmd(target_dir: Path | None) -> None:
    """Capture a secret-scrubbed snapshot of harness state into one tarball."""
    from harness.panic import panic_dump
    p = panic_dump(target_dir=target_dir)
    click.echo(f"panic-dump written: {p}")
    click.echo(f"size: {p.stat().st_size} bytes")


@cli.command(name="swarm-verify")
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


@cli.command()
@click.argument("subcmd", required=False)
@click.option("--list", "list_", is_flag=True, help="List engines.")
@click.option("--health", is_flag=True, help="Check engine health.")
def engines(subcmd: str | None, list_: bool, health: bool) -> None:
    """Query or modify the engine pool.

    W4-H 2026-05-22: accept either ``engines --list`` (original flag) or
    ``engines list`` (subcommand-style guess from W4-G campaign).  Same
    for ``engines health`` ↔ ``engines --health``.  No-arg invocation
    defaults to listing.
    """
    # Normalise subcommand-style guesses into flag-style
    if subcmd == "list":
        list_ = True
    elif subcmd == "health":
        health = True
    elif subcmd is not None:
        click.echo(f"Error: unknown subcommand {subcmd!r}; use 'list' or 'health' "
                   f"(or --list / --health flags)", err=True)
        sys.exit(2)

    state = read_engine_health()

    if health:
        probes = probe_all_engines()
        for name, (st, err) in probes.items():
            click.echo(f"{name}: {st}" + (f" ({err})" if err else ""))
        sys.exit(0)

    # Default / --list
    for name in ["deepseek", "kimi", "anthropic", "gemini"]:
        cfg = state.get(name)
        if cfg:
            click.echo(
                f"{name}: priority={cfg.priority} locked={cfg.locked} "
                f"status={cfg.status}"
            )
        else:
            click.echo(f"{name}: priority=NORMAL locked=False status=up")
    sys.exit(0)


@cli.command(name="engines-reliability")
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


@cli.command(name="engines-cooldowns")
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


@cli.command()
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


@cli.command()
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
    """Remove observer Windows Task Scheduler entries (chat + cycle + retro + db + cost when present)."""
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
              default=Path("coord/dev_loop/state.json"))
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
              default=Path("coord/dev_loop/state.json"))
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
              default=Path("coord/dev_loop/state.json"))
@click.option("--project-root", type=click.Path(path_type=Path),
              default=Path.cwd())
def loop_tick_cmd(state_path: Path, project_root: Path) -> None:
    """Run one tick of the autonomous loop."""
    from datetime import datetime, timezone
    from harness.loops.runner import tick as _tick

    try:
        result = _tick(
            state_path=state_path,
            observer_dir=Path("coord/observer"),
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
              default=Path("coord/dev_loop/state.json"))
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


@cli.command(name="replay")
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
    """Tabular ledger output."""
    entries = read_ledger(DEFAULT_LEDGER_PATH)
    if since:
        entries = [e for e in entries if e.timestamp >= since]
    if engine:
        entries = [e for e in entries if e.engine == engine]
    if not entries:
        click.echo("(no entries)")
        sys.exit(0)
    for e in entries:
        click.echo(f"{e.timestamp}  {e.engine:12}  {e.task_id:20}  ${e.cost_usd:.6f}")
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
    for eng, data in sorted(agg.items()):
        click.echo(
            f"{eng:12}  dispatches={int(data['dispatches'])}  "
            f"cost=${data['total_cost_usd']:.6f}  "
            f"in={int(data['total_input_tokens'])}  out={int(data['total_output_tokens'])}"
        )
        total += data["total_cost_usd"]
    click.echo(f"{'total':12}  ${total:.6f}")
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
    """Write monthly cap to coord/dev_loop/budget_cap.json."""
    DEFAULT_CAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CAP_PATH.write_text(
        json.dumps({"monthly_cap_usd": amount_usd}, indent=2),
        encoding="utf-8",
    )
    click.echo(f"monthly cap set to ${amount_usd:.2f}")
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


@cli.group(name="proxy")
def proxy_group() -> None:
    """Stateful 4-key API proxy with circuit breaker."""


@proxy_group.command(name="start")
@click.option("--port", default=7879, type=int)
@click.option("--host", default="127.0.0.1")
def proxy_start(port: int, host: str) -> None:
    """Start the proxy server in the background."""
    from harness.proxy.cli import start
    start(port=port, host=host)


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
    """Coordinator commands: plan, run, integrate, status."""


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
