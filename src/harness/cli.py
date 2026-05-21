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
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import click
import yaml

from harness.adapters.loader import _repo_root, load_project_adapter, load_template
from harness.cli_helpers import probe_all_engines
from harness.engines.dispatcher import dispatch_packet
from harness.operator import OperatorMode, resolve_operator_config
from harness.operator.flags import OPERATOR_FLAG_NAMES, apply_operator_flags
from harness.state.files import read_engine_health, update_engine_health

# Observer primitive (roster #20)
from harness.observer.cycle import run_cycle, CycleReport
from harness.observer.flags import (
    Flag,
    FlagSeverity,
    ensure_flag_dirs,
    list_pending_flags,
    ack_flag,
    move_pending_to_handled,
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


main = cli


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
    import csv as csv_mod
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
    """Check which API keys are set (echo SET only)."""
    from harness.secrets.dpapi import has_secret

    keys = ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"]
    for key_name in keys:
        if os.environ.get(key_name) or has_secret(key_name):
            click.echo(f"{key_name}: SET")
        else:
            click.echo(f"{key_name}: MISSING")
    sys.exit(0)


@cli.command()
@click.option("--port", default=7878, type=int, help="Dashboard server port.")
def dashboard_serve(port: int) -> None:
    """Start FastAPI dashboard server."""
    click.echo("dashboard-serve: pending Wave 3 (FastAPI + WebSocket)")
    sys.exit(1)


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
@click.option("--list", "list_", is_flag=True, help="List engines.")
@click.option("--health", is_flag=True, help="Check engine health.")
def engines(list_: bool, health: bool) -> None:
    """Query or modify the engine pool."""
    state = read_engine_health()

    if health:
        probes = probe_all_engines()
        for name, (st, err) in probes.items():
            click.echo(f"{name}: {st}" + (f" ({err})" if err else ""))
        sys.exit(0)

    # Default / --list
    for name in ["deepseek", "kimi", "anthropic"]:
        cfg = state.get(name)
        if cfg:
            click.echo(
                f"{name}: priority={cfg.priority} locked={cfg.locked} "
                f"status={cfg.status}"
            )
        else:
            click.echo(f"{name}: priority=NORMAL locked=False status=up")
    sys.exit(0)


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
@click.pass_context
def observer_cycle_now(ctx: click.Context, engine: str, audit_window: int) -> None:
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

    report = run_cycle(engine=engine, audit_window_minutes=audit_window)

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
def observer_install_scheduler(cadence_minutes: int, daily_time: str) -> None:
    """Register Windows Task Scheduler entries for the observer."""
    ok, msg = register_tasks(cadence_minutes=cadence_minutes, daily_time=daily_time)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@observer.command(name="uninstall-scheduler")
def observer_uninstall_scheduler() -> None:
    """Remove observer Windows Task Scheduler entries."""
    ok, msg = unregister_tasks()
    click.echo(msg)
    sys.exit(0 if ok else 1)
