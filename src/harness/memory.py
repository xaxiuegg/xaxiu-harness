"""W5-S — engine-agnostic memory store.

Reads `memory/*.md` files from the repo root and returns them as
operator-curated knowledge entries.  Used by:
- Worker `_build_prompt` to auto-include relevant memory in dispatch
  packets so the engine has operator context.
- `harness memory` CLI verbs (list / show / search).
- Future orchestrator daemon to seed its own context.

Design goals
------------
- Engine-agnostic: any LLM reads the same plain markdown.
- Cheap to inject: full memory ~5-15KB; fits in any engine's context.
- No required schema beyond filename + content; operator-friendly.
- Read-only: this module never modifies memory files (operator
  curates manually or via a future `harness memory edit` verb).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MemoryEntry:
    """One memory file's metadata + content."""

    name: str          # filename without .md extension
    path: Path         # absolute path
    title: str         # first H1 heading or filename if missing
    content: str       # full file body (markdown)
    size_bytes: int    # len(content.encode("utf-8"))


def memory_dir(repo_root: Path | None = None) -> Path:
    """Return the canonical memory/ directory location."""
    return (repo_root or Path.cwd()) / "memory"


def _extract_title(content: str, fallback: str) -> str:
    """Parse first '# ' heading as title, or return fallback."""
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def load_all(repo_root: Path | None = None) -> list[MemoryEntry]:
    """Return all memory/*.md entries, sorted by name.

    Best-effort: unreadable / malformed files are skipped silently.
    Missing memory/ directory returns [].
    """
    mdir = memory_dir(repo_root)
    if not mdir.exists() or not mdir.is_dir():
        return []
    entries: list[MemoryEntry] = []
    for md_path in sorted(mdir.glob("*.md")):
        try:
            content = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # malformed encoding or unreadable → skip
        name = md_path.stem
        title = _extract_title(content, fallback=name)
        entries.append(MemoryEntry(
            name=name, path=md_path, title=title,
            content=content,
            size_bytes=len(content.encode("utf-8")),
        ))
    return entries


def find_by_name(name: str, repo_root: Path | None = None) -> MemoryEntry | None:
    """Look up one memory entry by name (without .md).  None if missing."""
    for e in load_all(repo_root):
        if e.name == name:
            return e
    return None


def search(query: str, repo_root: Path | None = None) -> list[MemoryEntry]:
    """Return entries whose name, title, OR content contains *query* (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return []
    matches: list[MemoryEntry] = []
    for e in load_all(repo_root):
        if (q in e.name.lower()
                or q in e.title.lower()
                or q in e.content.lower()):
            matches.append(e)
    return matches


def format_for_packet(
    entries: list[MemoryEntry] | None = None,
    *,
    repo_root: Path | None = None,
    max_total_bytes: int = 15_000,
) -> str:
    """Render memory entries as a markdown section for a dispatch packet.

    Used by worker `_build_prompt` to inject memory before the task
    instruction.  Truncates if combined size exceeds max_total_bytes
    (default 15KB ≈ ~4k tokens) to leave room for the task itself.

    Returns "" when no memory exists (graceful for fresh installs).
    """
    if entries is None:
        entries = load_all(repo_root)
    if not entries:
        return ""

    lines = [
        "## Operator-curated memory (engine-agnostic knowledge)",
        "",
        "Read this before composing your output.  These files capture",
        "operator standing decisions, conventions, and engine quirks.",
        "",
    ]
    total = sum(len(l.encode("utf-8")) for l in lines)
    for e in entries:
        block = f"\n### memory/{e.name}.md\n\n{e.content}\n"
        block_bytes = len(block.encode("utf-8"))
        if total + block_bytes > max_total_bytes:
            lines.append(f"\n*(memory truncated at {max_total_bytes} bytes; "
                         f"{len(entries)} files total; remaining files "
                         f"available via `harness memory show <name>`)*\n")
            break
        lines.append(block)
        total += block_bytes
    return "\n".join(lines)
