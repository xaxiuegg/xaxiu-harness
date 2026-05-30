"""adapter create — scaffold a new project's adapter + coord layout."""

from __future__ import annotations

from pathlib import Path

import yaml as _yaml

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
      <target>/<name>/spec/.gitkeep
      <target>/<name>/runs/.gitkeep

    Returns a dict of the written paths.  Raises if the target already
    exists (refuses to overwrite operator state).

    PATH-A-TRIM 2026-05-29: no longer seeds coord/dev_loop/state.json — the
    autonomous dev-loop machinery was deleted in the harness retirement.
    """
    from harness.adapters.loader import load_template

    project_root = project_root or Path.cwd()
    project_dir = Path(target_dir) / project_name

    if project_dir.exists():
        raise FileExistsError(f"target already exists: {project_dir}")
    project_dir.mkdir(parents=True)

    # 1. Adapter yaml from template
    cfg = load_template(template, project_root=str(project_dir.resolve()))
    adapter_dir = project_dir / "adapters" / project_name
    adapter_dir.mkdir(parents=True)
    adapter_yaml = adapter_dir / "harness-adapter.yaml"
    # Re-emit as YAML — use the model's dump
    cfg_data = cfg.model_dump(mode="json")
    cfg_data["name"] = project_name
    adapter_yaml.write_text(
        _yaml.safe_dump(cfg_data, sort_keys=False),
        encoding="utf-8",
    )

    # 2. Empty STATUS.csv header
    coord_dir = project_dir / "coord"
    coord_dir.mkdir()
    (coord_dir / "STATUS.csv").write_text(
        "ID,Category,Title,Status,Owner,Effort,Updated,Notes\n",
        encoding="utf-8",
    )

    # 3. spec/ + runs/ placeholders
    (project_dir / "spec").mkdir()
    (project_dir / "spec" / ".gitkeep").write_text("", encoding="utf-8")
    (project_dir / "runs").mkdir()
    (project_dir / "runs" / ".gitkeep").write_text("", encoding="utf-8")

    return {
        "project_dir": project_dir,
        "adapter_yaml": adapter_yaml,
        "status_csv": coord_dir / "STATUS.csv",
    }
