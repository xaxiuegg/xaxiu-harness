"""W11-DPAPI-CROSS-PLATFORM: .env file parser + writer for cross-platform secrets.

The harness's DPAPI store is Windows-only.  For agentic coding agents
running on Linux/Mac (containers, CI, dev machines without DPAPI),
.env files are the universal secrets-at-rest path.

Schema (minimal subset of dotenv format):
    # comments ok
    KEY=value
    KEY2="quoted value"
    KEY3=value with spaces  (no quotes needed)

Doesn't support: variable substitution ($VAR), multi-line values,
inline export keyword.  Operators wanting those reach for python-dotenv
directly; we keep this dependency-free.
"""

from __future__ import annotations

from pathlib import Path


# -- read --


def read_env_file(path: Path | str) -> dict[str, str]:
    """Parse a .env file into a dict.  Missing file → empty dict (not raise).

    Malformed lines (no `=`) are silently skipped — operators often have
    comments + section headers + the parser shouldn't crash on them.
    """
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Optional `export KEY=val` prefix is silently stripped
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Strip matching outer quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        out[key] = value
    return out


def get_key(name: str, path: Path | str) -> str | None:
    """Convenience: read a single key from a .env file."""
    val = read_env_file(path).get(name)
    if val == "" or val is None:
        # Treat empty values as missing (operator left the template default)
        return None
    return val


# -- write --


def write_key(name: str, value: str, path: Path | str) -> None:
    """Set *name* to *value* in the .env file at *path*.

    Idempotent: existing entries get their value replaced; new entries
    are appended; the rest of the file is preserved verbatim (including
    comments + ordering).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"{name}={value}\n", encoding="utf-8")
        return
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    replaced = False
    out_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        # Skip comments / blank lines unchanged
        if not line or line.startswith("#"):
            out_lines.append(raw_line)
            continue
        # Strip optional export prefix for the key check
        check_line = line
        if check_line.startswith("export "):
            check_line = check_line[len("export "):].lstrip()
        existing_key = check_line.split("=", 1)[0].strip()
        if existing_key == name:
            # Replace this line, preserving line ending
            ending = "\r\n" if raw_line.endswith("\r\n") else "\n" if raw_line.endswith("\n") else ""
            out_lines.append(f"{name}={value}{ending}")
            replaced = True
        else:
            out_lines.append(raw_line)
    if not replaced:
        # Ensure trailing newline before appending
        if out_lines and not out_lines[-1].endswith(("\n", "\r\n")):
            out_lines.append("\n")
        out_lines.append(f"{name}={value}\n")
    p.write_text("".join(out_lines), encoding="utf-8")
