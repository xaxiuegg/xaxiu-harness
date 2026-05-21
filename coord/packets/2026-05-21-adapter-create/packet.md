# ADAPTER-CREATE — `harness adapter create <project-name>` scaffolding verb

## Goal

`harness install` sets up the harness host; porting harness to a new
project still requires manual copy of `coord/`, `spec/`, `adapter/`
templates.  Per `feedback_multi_session_scoping`, the operator runs
parallel Claude Code sessions one per project — each one repeats the
copy-paste ritual.

`harness adapter create <name>` scaffolds it.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/adapters/from_description.py` (or new module)

Prefer adding to an existing module to avoid module proliferation.  If
`src/harness/adapters/from_description.py` already has scaffolding
helpers, add the new function there.  Otherwise create
`src/harness/adapters/scaffold.py`:

```python
"""adapter create — scaffold a new project's adapter + coord layout."""

from __future__ import annotations

import shutil
from pathlib import Path


_DEFAULT_TEMPLATE = "basic"


def scaffold_adapter(
    project_name: str,
    *,
    target_dir: Path,
    template: str = _DEFAULT_TEMPLATE,
    project_root: Path | None = None,
) -> dict[str, Path]:
    """Scaffold a new project layout under *target_dir/project_name/*.

    Creates:
      <target>/<name>/adapters/<name>/harness-adapter.yaml (from template, placeholders resolved)
      <target>/<name>/coord/STATUS.csv (empty header only)
      <target>/<name>/coord/dev_loop/state.json (default LoopState)
      <target>/<name>/spec/.gitkeep
      <target>/<name>/runs/.gitkeep

    Returns a dict of the written paths.  Raises if the target already
    exists (refuses to overwrite operator state).
    """
    from harness.adapters.loader import load_template
    from harness.loops.state import LoopState, write_state

    project_root = project_root or Path.cwd()
    project_dir = Path(target_dir) / project_name

    if project_dir.exists():
        raise FileExistsError(f"target already exists: {project_dir}")
    project_dir.mkdir(parents=True)

    # 1. Adapter yaml from template
    cfg = load_template(template, project_root=str((project_dir).resolve()))
    adapter_dir = project_dir / "adapters" / project_name
    adapter_dir.mkdir(parents=True)
    adapter_yaml = adapter_dir / "harness-adapter.yaml"
    # Re-emit as YAML — use the model's dump
    import yaml as _yaml
    # Override the name field to match the requested project name
    cfg_data = cfg.model_dump(mode="json")
    cfg_data["name"] = project_name
    adapter_yaml.write_text(
        _yaml.safe_dump(cfg_data, sort_keys=False), encoding="utf-8",
    )

    # 2. Empty STATUS.csv header
    coord_dir = project_dir / "coord"
    coord_dir.mkdir()
    (coord_dir / "STATUS.csv").write_text(
        "ID,Category,Title,Status,Owner,Effort,Updated,Notes\n",
        encoding="utf-8",
    )

    # 3. dev_loop seed
    dev_loop = coord_dir / "dev_loop"
    dev_loop.mkdir()
    write_state(dev_loop / "state.json", LoopState())

    # 4. spec/ + runs/ placeholders
    (project_dir / "spec").mkdir()
    (project_dir / "spec" / ".gitkeep").write_text("", encoding="utf-8")
    (project_dir / "runs").mkdir()
    (project_dir / "runs" / ".gitkeep").write_text("", encoding="utf-8")

    return {
        "project_dir": project_dir,
        "adapter_yaml": adapter_yaml,
        "status_csv": coord_dir / "STATUS.csv",
        "state_json": dev_loop / "state.json",
    }
```

### 2. CLI subcommand

In `src/harness/cli.py`, find `@cli.group(name="adapter")` and its
existing subcommands.  Add a NEW sibling AFTER the existing
`from-description`:

```python
@adapter.command(name="create")
@click.argument("project_name")
@click.option("--target-dir", default=".", type=click.Path(path_type=Path),
              help="Parent dir for the new project (default cwd).")
@click.option("--template", default="basic",
              help="Adapter template name (basic | generic-coding | solo-dev | …).")
def adapter_create(project_name: str, target_dir: Path, template: str) -> None:
    """Scaffold a new project: adapter YAML + coord layout + spec/ + runs/."""
    from harness.adapters.scaffold import scaffold_adapter

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
```

### 3. Tests

`tests/test_adapter_create.py`:

```python
"""Tests for ADAPTER-CREATE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.adapters.scaffold import scaffold_adapter


def test_scaffold_creates_expected_layout(tmp_path: Path) -> None:
    paths = scaffold_adapter("my-project", target_dir=tmp_path)
    pdir = paths["project_dir"]
    assert pdir.exists()
    assert (pdir / "adapters" / "my-project" / "harness-adapter.yaml").exists()
    assert (pdir / "coord" / "STATUS.csv").exists()
    assert (pdir / "coord" / "dev_loop" / "state.json").exists()
    assert (pdir / "spec" / ".gitkeep").exists()
    assert (pdir / "runs" / ".gitkeep").exists()


def test_scaffold_status_csv_has_only_header(tmp_path: Path) -> None:
    scaffold_adapter("p", target_dir=tmp_path)
    text = (tmp_path / "p" / "coord" / "STATUS.csv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("ID,Category,Title,Status,")


def test_scaffold_refuses_existing_target(tmp_path: Path) -> None:
    (tmp_path / "existing").mkdir()
    with pytest.raises(FileExistsError):
        scaffold_adapter("existing", target_dir=tmp_path)


def test_scaffold_state_json_is_valid_loopstate(tmp_path: Path) -> None:
    from harness.loops.state import LoopState, read_state
    paths = scaffold_adapter("p", target_dir=tmp_path)
    state = read_state(paths["state_json"])
    assert isinstance(state, LoopState)
    assert state.loop_status == "armed"


def test_cli_adapter_create(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        result = runner.invoke(cli, [
            "adapter", "create", "my-project",
            "--target-dir", str(iso_path),
        ])
    assert result.exit_code == 0, result.output
    assert "created project:" in result.output
    assert "my-project" in result.output


def test_cli_adapter_create_refuses_existing(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as iso:
        iso_path = Path(iso)
        (iso_path / "dup").mkdir()
        result = runner.invoke(cli, [
            "adapter", "create", "dup",
            "--target-dir", str(iso_path),
        ])
    assert result.exit_code == 1
    assert "already exists" in result.output
```

## Acceptance

- `python -m pytest tests/test_adapter_create.py` — green.
- Full suite stays green.
- `harness adapter create my-test --target-dir /tmp` works end-to-end.

## Constraints

- DO NOT modify existing adapter templates.
- DO NOT touch `harness install`.
- Reuse `load_template` + `write_state` rather than re-implementing.
- Stdlib + yaml only.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
