r"""
Higher-level adapter loader with placeholder substitution, path validation,
and template loading.

# CI guard: ! grep -rn 'yaml\.load(' src/

Security guarantees
-------------------
* Templates are loaded from a whitelist of 5 canonical names (LOW-5).
* All YAML parsing is delegated to ``schema.load_adapter``, which uses
  ``yaml.safe_load`` exclusively (HIGH-7).
* ``project_root`` is validated to be absolute, existent, and not under
  Windows system directories (MED-2).
* Status-tracking file paths (``csv_path``, ``path``) are resolved and
  checked to stay inside ``project_root`` (MED-3).
* Validation errors raise ``ValueError`` that name the offending field but
  never echo file contents.

Canonical template names
--------------------------
* warehouse-style
* generic-coding
* writing-content
* research-comparison
* solo-dev
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from harness._constants import PROJECT_NAME_REGEX

from .schema import AdapterConfig, load_adapter

#: Canonical template names (v1.1 §2).
ALLOWED_TEMPLATES: frozenset[str] = frozenset(
    {
        "warehouse-style",
        "generic-coding",
        "writing-content",
        "research-comparison",
        "solo-dev",
        "basic",
    }
)

#: Regex for valid project names — sourced from _constants to align with
#: db.py's SQL-side validation (Wave 2A MED fix: avoids late silent failures
#: for names that loader accepts but db rejects).
_PROJECT_NAME_RE: re.Pattern[str] = re.compile(PROJECT_NAME_REGEX)

#: Windows system directories that ``project_root`` must not reside under.
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    os.environ.get("WINDIR", r"C:\Windows"),
    os.environ.get("PROGRAMFILES", r"C:\Program Files"),
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
)


def _repo_root() -> Path:
    """Return the repository root (directory containing ``src/``, ``adapters/``, etc.)."""
    # loader.py lives at <repo_root>/src/harness/adapters/loader.py
    return Path(__file__).resolve().parents[3]


def _validate_project_root(project_root: str) -> Path:
    """
    Run MED-2 checks on ``project_root``.

    Returns the resolved ``Path`` on success.
    Raises ``ValueError`` on any failure.
    """
    p = Path(project_root)
    if not p.is_absolute():
        raise ValueError("project_root must be an absolute path")

    try:
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"project_root does not exist or is not accessible: {exc}"
        ) from exc

    if not resolved.is_dir():
        raise ValueError("project_root must be an existing directory")

    # Case-insensitive check on Windows
    for forbidden_str in _FORBIDDEN_PREFIXES:
        forbidden = Path(forbidden_str).resolve()
        try:
            is_under = resolved.is_relative_to(forbidden)
        except ValueError:
            is_under = False
        if is_under:
            raise ValueError(
                "project_root must not be under system directories"
            )

    return resolved


def _validate_status_path(cfg: AdapterConfig, root_resolved: Path) -> None:
    """
    Run MED-3 check: status-tracking file path must resolve inside
    ``project_root``.
    """
    backend = cfg.status_tracking.backend
    config = cfg.status_tracking.config

    if backend == "csv":
        rel_path = config.get("csv_path", "STATUS.csv")
        field_name = "status_tracking.config.csv_path"
    elif backend == "markdown":
        rel_path = config.get("path", "STATUS.md")
        field_name = "status_tracking.config.path"
    else:
        # jira / linear – no local file path to validate
        return

    if not isinstance(rel_path, str):
        raise ValueError(f"{field_name} must be a string")

    target = (root_resolved / rel_path).resolve()
    try:
        if not target.is_relative_to(root_resolved):
            raise ValueError(f"{field_name} escapes project_root")
    except ValueError:
        raise ValueError(f"{field_name} escapes project_root") from None


def _run_path_security_checks(cfg: AdapterConfig) -> None:
    """
    Execute all path security checks on a parsed ``AdapterConfig``.

    Raises ``ValueError`` on the first failure.
    """
    root_resolved = _validate_project_root(cfg.project_root)
    _validate_status_path(cfg, root_resolved)


def resolve_placeholders(yaml_text: str, project_root: str) -> str:
    """
    Replace literal ``{{PROJECT_ROOT}}`` with *project_root*.

    Uses ``str.replace`` (never format-string interpolation) so that
    user-supplied YAML cannot accidentally be interpreted as a template.
    Backslashes in the path are normalised to forward slashes for safe
    YAML embedding on Windows.
    """
    safe_root = project_root.replace("\\", "/")
    return yaml_text.replace("{{PROJECT_ROOT}}", safe_root)


def list_templates() -> list[str]:
    """Return the canonical 5-name template list."""
    return sorted(ALLOWED_TEMPLATES)


def load_template(name: str, project_root: str | None = None) -> AdapterConfig:
    """
    Load a canonical template by name, optionally substituting placeholders.

    Args:
        name: One of the five canonical template names.
        project_root: If given, ``{{PROJECT_ROOT}}`` placeholders are replaced.

    Returns:
        Validated ``AdapterConfig``.

    Raises:
        ValueError: If the template name is not whitelisted.
        FileNotFoundError: If the template file does not exist.
    """
    if name not in ALLOWED_TEMPLATES:
        raise ValueError(
            f"Unknown template: {name}. Valid: {sorted(ALLOWED_TEMPLATES)}"
        )

    template_path = _repo_root() / "adapters" / "templates" / f"{name}.yaml"
    if not template_path.exists():
        raise FileNotFoundError(str(template_path))

    yaml_text = template_path.read_text(encoding="utf-8")

    if project_root is not None:
        yaml_text = resolve_placeholders(yaml_text, project_root)

    # yaml.safe_load is the canonical loader (HIGH-7)
    data = yaml.safe_load(yaml_text)
    if data is None:
        raise ValueError("YAML file is empty or contains only comments")

    try:
        cfg = AdapterConfig.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Adapter validation failed: {exc}") from exc

    # Path security checks require resolved placeholders
    if project_root is not None:
        _run_path_security_checks(cfg)
    return cfg


def load_project_adapter(project_name: str) -> AdapterConfig:
    """
    Load a project-specific adapter YAML.

    Args:
        project_name: Alphanumeric, hyphens, and underscores; 1-64 chars.

    Returns:
        Validated ``AdapterConfig``.

    Raises:
        ValueError: If *project_name* is malformed or security checks fail.
        FileNotFoundError: If the adapter file does not exist.
    """
    if not _PROJECT_NAME_RE.fullmatch(project_name):
        raise ValueError(
            "project_name must match ^[a-zA-Z0-9_-]{1,64}$"
        )

    adapter_path = (
        _repo_root() / "adapters" / project_name / "harness-adapter.yaml"
    )
    if not adapter_path.exists():
        raise FileNotFoundError(str(adapter_path))

    # Resolve ``{{PROJECT_ROOT}}`` against the repo root so in-tree planner /
    # worker adapters are portable across operator clones.  External-project
    # adapters that hardcode an absolute path are unaffected.
    yaml_text = resolve_placeholders(
        adapter_path.read_text(encoding="utf-8"),
        str(_repo_root()),
    )
    data = yaml.safe_load(yaml_text)
    if data is None:
        raise ValueError("YAML file is empty or contains only comments")
    try:
        cfg = AdapterConfig.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Adapter validation failed: {exc}") from exc

    _run_path_security_checks(cfg)
    return cfg
