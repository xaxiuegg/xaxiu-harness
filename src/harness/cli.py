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

from harness.adapters.from_description import generate_adapter_from_nl
from harness.adapters.loader import _repo_root, load_project_adapter, load_template
from harness.cli_helpers import probe_all_engines
from harness.engines.dispatcher import dispatch_packet
from harness.operator import OperatorMode, resolve_operator_config
from harness.operator.flags import OPERATOR_FLAG_NAMES, apply_operator_flags
from harness.state.files import read_engine_health, update_engine_health

# Budget primitive (BUDGET-METER)
from harness.budget import (
    DEFAULT_CAP_PATH,
    DEFAULT_LEDGER_PATH,
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
@click.option("--include-chat", is_flag=True,
              help="Also register the chat-observer audit task (CHAT-OBSERVER).")
def observer_install_scheduler(cadence_minutes: int, daily_time: str, include_chat: bool) -> None:
    """Register Windows Task Scheduler entries for the observer."""
    ok, msg = register_tasks(cadence_minutes=cadence_minutes, daily_time=daily_time, include_chat=include_chat)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@observer.command(name="uninstall-scheduler")
def observer_uninstall_scheduler() -> None:
    """Remove observer Windows Task Scheduler entries."""
    ok, msg = unregister_tasks()
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
        click.echo(f"error: {exc.tag()}: {exc.message}", err=True)
        sys.exit(exc.exit_code())


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
@click.option("--since", default="this-month")
def budget_summary_cmd(since: str) -> None:
    """Per-engine totals + grand total."""
    since_iso = None
    if since == "this-month":
        since_iso = datetime.now(timezone.utc).strftime("%Y-%m")
    else:
        since_iso = since
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


@coord_group.command(name="run")
@click.option("--spec", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--run-id", default=None, help="Run ID (defaults to auto-generated).")
@click.option("--resume", is_flag=True, help="Resume the latest run.")
@click.option("--limit", default=None, type=int, help="In-flight worker limit.")
@click.option("--proxy", type=click.Choice(["auto", "off", "external"]),
              default="auto",
              help="Auto-start the v2 proxy ('auto'), use a running one ('external'), or skip ('off').")
def coord_run(spec: Path, run_id: str | None, resume: bool, limit: int | None, proxy: str) -> None:
    """Execute a coordination run (single tick)."""
    from harness.coord.coordinator import Coordinator
    from harness.coord.planner import _new_run_id
    from harness.coord.run_state import read_run_state
    from harness.proxy import lifecycle as proxy_lifecycle

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
        coord = Coordinator(run_id=rid, run_dir=run_dir)
        report = coord.tick(spec, in_flight_limit=limit)
        click.echo(f"run {report.run_id}: {report.state.value}")
        if report.worker_summary:
            for wid, st in report.worker_summary.items():
                click.echo(f"  {wid}: {st}")
        sys.exit(0 if report.state.value in ("completed", "running") else 1)
    finally:
        if proxy_proc is not None:
            proxy_lifecycle.stop_proxy(proxy_proc)


@coord_group.command(name="work")
@click.option("--run-id", required=True)
@click.option("--worker-id", required=True)
@click.option("--engine", default="swarm/kimi-api")
def coord_work(run_id: str, worker_id: str, engine: str) -> None:
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

    result = run_worker(task.model_dump(), run_dir, engine=engine)
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
def coord_integrate(run_id: str, project_root: Path, commit: bool, push: bool) -> None:
    """Integrate a completed run: tests, commit, push."""
    from harness.coord.integrator import integrate
    run_dir = Path("runs") / run_id
    report = integrate(run_dir, project_root=project_root, auto_commit=commit, auto_push=push)
    click.echo(f"integrate: success={report.success} commit={report.commit_sha} pushed={report.pushed}")
    if report.diagnostic:
        click.echo(f"  diagnostic: {report.diagnostic}")
    if report.test_summary:
        click.echo(f"  tests: {report.test_summary}")
    sys.exit(0 if report.success else 1)


@coord_group.command(name="list")
@click.option("--limit", default=20, type=int, help="Max number of runs to print (newest first).")
def coord_list(limit: int) -> None:
    """List runs/ with state + age + worker count (CLI parity for /v2/runs)."""
    from harness.dashboard.v2_routes import list_runs
    runs = list_runs()
    if not runs:
        click.echo("no runs")
        return
    # Sort newest first by last_tick_at, falling back to started_at, then run_id
    def _key(r: dict) -> str:
        return r.get("last_tick_at") or r.get("started_at") or r.get("run_id", "")
    runs_sorted = sorted(runs, key=_key, reverse=True)[:limit]
    click.echo(f"{'RUN_ID':<28} {'STATE':<14} {'TASKS':>5}  STARTED_AT")
    for r in runs_sorted:
        click.echo(
            f"{r['run_id']:<28} {str(r.get('state') or '-'):<14} "
            f"{r.get('tasks', 0):>5}  {r.get('started_at') or '-'}"
        )


@coord_group.command(name="status")
@click.option("--run-id", required=True)
def coord_status(run_id: str) -> None:
    """Show run state summary."""
    from harness.coord.run_state import read_run_state
    run_dir = Path("runs") / run_id
    state = read_run_state(run_dir / "run_state.json")
    if state is None:
        click.echo("error: run not found")
        raise SystemExit(1)
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
