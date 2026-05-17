# Packet: Wave 2A / Adapter YAML loader

## Mission
Produce `src/harness/adapters/loader.py` — a higher-level adapter loader that wraps `schema.py`'s `load_adapter()` with placeholder substitution, path validation, and template loading. Implements v1.2 amendments HIGH-7 (yaml.safe_load), MED-2 (project_root validation), MED-3 (csv_path traversal prevention), LOW-5 (template name whitelist).

## Required API

```python
def load_template(name: str, project_root: str | None = None) -> AdapterConfig: ...
def load_project_adapter(project_name: str) -> AdapterConfig: ...
def list_templates() -> list[str]: ...
def resolve_placeholders(yaml_text: str, project_root: str) -> str: ...
```

## Implementation details

### `load_template(name, project_root)`
- Validate `name` against the EXACT list of 5 template names: `warehouse-style`, `generic-coding`, `writing-content`, `research-comparison`, `solo-dev`. Reject any other value with `ValueError(f"Unknown template: {name}. Valid: {ALLOWED_TEMPLATES}")`.
- Read template YAML text from `<repo_root>/adapters/templates/<name>.yaml`. (Templates ship in a later wave; if file is missing, raise `FileNotFoundError` with the expected path.)
- If `project_root` provided, call `resolve_placeholders(yaml_text, project_root)` before parsing.
- Pass resolved text through `schema.load_adapter` (which enforces yaml.safe_load).
- Apply path security checks below before returning.

### `load_project_adapter(project_name)`
- Validate `project_name` against regex `r"^[a-zA-Z0-9_-]{1,64}$"` — reject otherwise.
- Read from `<repo_root>/adapters/<project_name>/harness-adapter.yaml`.
- Validate via `schema.load_adapter`.
- Apply path security checks below.

### Path security checks (run on every load)
1. **project_root absolute**: `Path(cfg.project_root).is_absolute()` must be True. Reject otherwise.
2. **project_root exists + is dir**: `Path(cfg.project_root).resolve(strict=True).is_dir()`. Reject if not.
3. **project_root not under Windows system dirs**: resolved path MUST NOT have `os.environ.get("WINDIR", "C:\\Windows")`, `"Program Files"`, or `"ProgramData"` as an ancestor (case-insensitive on Windows). Reject otherwise.
4. **status_tracking file path under project_root**: for `cfg.status_tracking.backend == "csv"`, resolve `cfg.status_tracking.config.get("csv_path", "STATUS.csv")` against `project_root`. The resolved path MUST satisfy `resolved.is_relative_to(project_root_resolved)`. Same for `markdown` backend (`path` key).
5. All checks raise `ValueError` (NOT `OSError` or naked exceptions) with a clear message that mentions the field but not the file contents.

### `list_templates()`
- Returns the canonical 5-name list as a tuple or list constant (defined at module top).

### `resolve_placeholders(yaml_text, project_root)`
- Replace literal `{{PROJECT_ROOT}}` with `project_root`. Use `str.replace` (NOT format-string — placeholder might appear in user-supplied YAML).
- For Windows paths: backslashes must be either YAML-escaped or the function should output forward slashes (preferable since PathLib handles both).

## CRITICAL security requirements
1. Use `yaml.safe_load` exclusively (delegated via `schema.load_adapter`). Add a defensive grep-comment at top of file: `# CI guard: ! grep -rn 'yaml\.load(' src/`
2. Reject project_root under Windows system directories (HIGH).
3. Reject status backend file paths that escape project_root via `..` (MED-3).
4. Reject template names outside the 5-name whitelist (LOW-5).
5. Validation errors raise `ValueError` with field name but NEVER file contents.

## Output format
Single Python file at `D:/Projects/xaxiu-harness/src/harness/adapters/loader.py`. Target 150-250 lines. Type-hint. Imports: stdlib (`os`, `pathlib`, `re`) + `from .schema import AdapterConfig, load_adapter` (relative import).

Include module docstring explaining contract + template name list + security guarantees.

## Reference
- v1.2 amendments HIGH-7, MED-2, MED-3, LOW-5
- `src/harness/adapters/schema.py` (already implemented, exports `load_adapter` + `AdapterConfig`)
- v1.1 §2 (canonical 5 template names)
