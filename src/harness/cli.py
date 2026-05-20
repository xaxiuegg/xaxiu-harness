"""xaxiu-harness CLI.

Cross-project multi-engine LLM dispatch + monitoring tool.
All commands are currently stubbed for Wave 1 scaffolding.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import click

from harness.engines.dispatcher import dispatch_packet


@click.group()
def cli() -> None:
    """xaxiu-harness: dispatch, observe, and retro across LLM engines."""


main = cli


@cli.command()
@click.option("--project", "-p", help="Project name (maps to adapter).")
@click.option("--packet", help="Path to dispatch packet markdown file.")
@click.option("--backend", "-b", help="Override backend engine.")
@click.option("--model", "-m", help="Override model name.")
@click.option("--force-engine", help="Force a specific engine (disables routing).")
def dispatch(
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


@cli.command()
@click.option("--project", "-p", help="Project name.")
@click.option("--report", is_flag=True, help="Report to configured backend.")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), help="Output format.")
def status(project: Optional[str], report: bool, fmt: Optional[str]) -> None:
    """Print current status (or report to configured backend)."""
    click.echo(f"status: project={project} report={report} format={fmt}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.option("--project", "-p", help="Project name.")
def observer_tick(project: Optional[str]) -> None:
    """Run one observer cycle: check status changes, flag patterns."""
    click.echo(f"observer-tick: project={project}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.option("--project", "-p", help="Project name.")
@click.option("--date", help="Retro date (YYYY-MM-DD).")
def retro(project: Optional[str], date: Optional[str]) -> None:
    """Generate daily retro summary from history."""
    click.echo(f"retro: project={project} date={date}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.option("--uninstall", is_flag=True, help="Remove scheduled tasks and config.")
def install(uninstall: bool) -> None:
    """Setup Task Scheduler entries and first-run wizard."""
    click.echo(f"install: uninstall={uninstall}")
    click.echo("not implemented yet")
    sys.exit(0)


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
    default="basic",
    help="Starter template.",
)
def init(project: str, template: str) -> None:
    """Create starter adapter YAML for a project."""
    click.echo(f"init: would create template {template} for project {project}")
    sys.exit(0)


@cli.command()
@click.option("--show-set", is_flag=True, help="Show which API keys are set.")
def env(show_set: bool) -> None:
    """Check which API keys are set (echo SET only)."""
    keys = ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"]
    for key_name in keys:
        val = os.environ.get(key_name)
        if val:
            click.echo(f"{key_name}: SET")
        else:
            click.echo(f"{key_name}: MISSING")
    sys.exit(0)


@cli.command()
@click.option("--port", default=7878, type=int, help="Dashboard server port.")
def dashboard_serve(port: int) -> None:
    """Start FastAPI dashboard server."""
    click.echo(f"dashboard-serve: port={port}")
    click.echo("not implemented yet")
    sys.exit(0)


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
    click.echo(f"loops: project={project} add={add} remove={remove}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.option("--list", "list_", is_flag=True, help="List engines.")
@click.option("--health", is_flag=True, help="Check engine health.")
@click.option("--priority", nargs=2, help="Set engine priority: ENGINE PRIORITY.")
@click.option("--burst", nargs=2, help="Burst engine: ENGINE DURATION.")
@click.option("--lock", help="Lock engine.")
@click.option("--release", is_flag=True, help="Release engine lock.")
def engines(
    list_: bool,
    health: bool,
    priority: Optional[tuple[str, str]],
    burst: Optional[tuple[str, str]],
    lock: Optional[str],
    release: bool,
) -> None:
    """Query or modify the engine pool."""
    click.echo(
        f"engines: list={list_} health={health} priority={priority} burst={burst} lock={lock} release={release}"
    )
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.argument("engine")
@click.argument("level", type=click.Choice(["HIGH", "NORMAL", "AVOID"]))
def priority(engine: str, level: str) -> None:
    """Set persistent routing priority per engine."""
    click.echo(f"priority: engine={engine} level={level}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.argument("engine")
@click.argument("duration_min", type=int)
def burst(engine: str, duration_min: int) -> None:
    """Temporarily route all traffic to one engine."""
    click.echo(f"burst: engine={engine} duration_min={duration_min}")
    click.echo("not implemented yet")
    sys.exit(0)


@cli.command()
@click.argument("engine")
@click.option("--release", is_flag=True, help="Release the lock.")
def lock(engine: str, release: bool) -> None:
    """Exclusive routing lock (disables auto-routing)."""
    click.echo(f"lock: engine={engine} release={release}")
    click.echo("not implemented yet")
    sys.exit(0)
