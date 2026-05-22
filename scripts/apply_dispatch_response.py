"""Apply FILE/REPLACE blocks from a dispatch response file to the main repo.

Usage:
    python -X utf8 scripts/apply_dispatch_response.py <response_md_path> [--dry-run]

Reuses harness.coord.worker._parse_file_edits and _apply_file_edits so the
parser stays consistent with the in-coord worker path.  Stops on first error
and reports which file/anchor failed so review can patch by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.coord.worker import _parse_file_edits, _apply_file_edits  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("response_path", type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = p.parse_args()

    text = args.response_path.read_text(encoding="utf-8")
    # Strip the HTML header comment if present
    text = re.sub(r"^\s*<!--[\s\S]*?-->\s*", "", text)

    edits = _parse_file_edits(text)
    if not edits:
        print(f"[apply] no FILE/REPLACE blocks found in {args.response_path}")
        return 1

    print(f"[apply] parsed {len(edits)} edit blocks")
    for i, (path, search, replace) in enumerate(edits, 1):
        kind = "create" if not search.strip() else "edit"
        print(f"  {i}. {kind:6s} {path}  "
              f"({len(search)} chars SEARCH → {len(replace)} chars REPLACE)")

    if args.dry_run:
        print("[apply] --dry-run; no writes.")
        return 0

    modified = _apply_file_edits(edits, args.repo_root)
    print(f"[apply] modified {len(modified)} files:")
    for m in modified:
        print(f"  - {m}")
    return 0 if len(modified) == len(edits) else 2


if __name__ == "__main__":
    raise SystemExit(main())
