"""W9-SILENT-EXCEPTION-AUDIT — walk the source tree, find every
silent-except pattern (`except X: pass` / `except X: continue`),
classify by exception scope, and emit a Markdown inventory.

The load-bearing audit case: W8 schema bug.  An ``except Exception:
continue`` in ``preflight.fix_dead_engines`` silently swallowed
Pydantic ValidationError on every quarantine write for an unknown
duration.  20+ master-audit reviewers flagged the pattern as one of
the highest-probability next failure modes.

Output: coord/reviews/silent-exception-audit.md  with three sections:
  - BROAD       (except Exception / BaseException — the high-risk
                 swallows that hide schema/I/O bugs)
  - TIGHT       (except specific-type — usually defensible cleanup)
  - DOCUMENTED  (any of the above that has an inline comment
                 within 3 lines justifying silence — the intended
                 ship-state for surviving instances)

Usage:
    PYTHONPATH=src python -X utf8 scripts/audit_silent_excepts.py
    PYTHONPATH=src python -X utf8 scripts/audit_silent_excepts.py --json  # for the lint test
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "harness"
HOT_PATH_DIRS = ("engines", "coord", "state", "proxy", "observer", "dispatch")
BROAD_EXC_TYPES = frozenset({"Exception", "BaseException"})


@dataclass
class SilentExcept:
    path: str
    lineno: int
    handler_types: list[str] = field(default_factory=list)
    body_op: str = "pass"          # "pass" or "continue"
    classification: str = "tight"  # "broad" or "tight"
    documented: bool = False       # has a comment within 3 lines above
    nearby_context: str = ""       # 1-line snippet for the report

    @property
    def is_hotpath(self) -> bool:
        return any(seg in self.path.replace("\\", "/").split("/")
                   for seg in HOT_PATH_DIRS)


def _gather_comments(src: str) -> dict[int, str]:
    """Return a dict mapping line-number -> stripped comment text."""
    out: dict[int, str] = {}
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            out[i] = stripped.lstrip("#").strip()
    return out


def _handler_type_names(handler: ast.ExceptHandler) -> list[str]:
    """Extract the textual exception-type names from an except handler."""
    t = handler.type
    if t is None:
        return ["BareExcept"]
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, ast.Tuple):
        names: list[str] = []
        for elt in t.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(ast.unparse(elt) if hasattr(ast, "unparse") else "?")
            else:
                names.append("?")
        return names
    if isinstance(t, ast.Attribute):
        return [ast.unparse(t) if hasattr(ast, "unparse") else "?"]
    return ["?"]


def find_silent_excepts(path: Path, src: str) -> list[SilentExcept]:
    """AST-walk *src* (the contents of *path*) and return all silent
    except patterns: handler body is exactly one stmt that is Pass()
    or Continue().

    "Documented" means any of:
    - Comment line within 3 lines above the ``except``
    - Trailing comment on the body line (e.g. ``pass  # best-effort``)
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    comments = _gather_comments(src)
    source_lines = src.splitlines()
    out: list[SilentExcept] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1:
            continue
        stmt = node.body[0]
        if isinstance(stmt, ast.Pass):
            op = "pass"
        elif isinstance(stmt, ast.Continue):
            op = "continue"
        else:
            continue
        types = _handler_type_names(node)
        is_broad = any(t in BROAD_EXC_TYPES for t in types)
        # Documented if there's a comment line in the 3 lines above
        # OR a trailing comment on the body line (pass  # ... / continue  # ...)
        documented = any(
            (node.lineno - k) in comments
            for k in (1, 2, 3)
        )
        if not documented:
            body_lineno = stmt.lineno
            try:
                body_line = source_lines[body_lineno - 1]
            except IndexError:
                body_line = ""
            # Trailing comment if there's a "#" anywhere after the
            # body keyword on that line.  Strip strings would be more
            # rigorous but pass/continue can't have string args, so a
            # simple "#" presence check is safe here.
            if "#" in body_line:
                # crude: only count if # appears AFTER the keyword
                after_kw = body_line.split(op, 1)
                if len(after_kw) == 2 and "#" in after_kw[1]:
                    documented = True
        # 1-line snippet of context: handler header
        try:
            snippet = source_lines[node.lineno - 1].strip()
        except IndexError:
            snippet = ""
        try:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            # Path is outside REPO_ROOT (e.g. test fixture under tmp_path)
            rel = str(path).replace("\\", "/")
        out.append(SilentExcept(
            path=rel,
            lineno=node.lineno,
            handler_types=types,
            body_op=op,
            classification="broad" if is_broad else "tight",
            documented=documented,
            nearby_context=snippet,
        ))
    return out


def scan_repo() -> list[SilentExcept]:
    all_findings: list[SilentExcept] = []
    for p in sorted(SRC_ROOT.rglob("*.py")):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        all_findings.extend(find_silent_excepts(p, src))
    return all_findings


def format_report(findings: list[SilentExcept]) -> str:
    broad = [f for f in findings if f.classification == "broad"]
    broad_hot = [f for f in broad if f.is_hotpath]
    broad_undoc = [f for f in broad_hot if not f.documented]
    tight = [f for f in findings if f.classification == "tight"]
    tight_hot = [f for f in tight if f.is_hotpath]

    lines = [
        "# Silent-except inventory (W9-SILENT-EXCEPTION-AUDIT)",
        "",
        "_Generated by `scripts/audit_silent_excepts.py`._",
        "",
        f"- Total silent-except sites: **{len(findings)}**",
        f"- Broad (`except Exception/BaseException`): **{len(broad)}**",
        f"- Broad in hot-path (engines/coord/state/proxy/observer/dispatch): "
        f"**{len(broad_hot)}**",
        f"- Broad in hot-path WITHOUT inline justification comment: "
        f"**{len(broad_undoc)}**",
        f"- Tight (specific exception types): **{len(tight)}** "
        f"({len(tight_hot)} in hot-path)",
        "",
        "## Why this matters",
        "",
        "W8 hit a load-bearing schema bug because `except Exception: "
        "continue` in `preflight.fix_dead_engines` silently swallowed "
        "Pydantic ValidationError on every quarantine write.  20+ "
        "master-audit reviewers flagged broad silent excepts as the "
        "highest-probability next failure mode.",
        "",
        "## BROAD in hot-path WITHOUT justification (highest risk)",
        "",
        "These should each get either (a) `logger.warning(exc)`, (b) "
        "a typed `HarnessError` re-raise, or (c) an inline comment "
        "explaining why silence is intentional.",
        "",
        "| File | Line | Handler | Body | Context |",
        "|---|---|---|---|---|",
    ]
    for f in sorted(broad_undoc, key=lambda x: (x.path, x.lineno)):
        types = " / ".join(f.handler_types)
        lines.append(
            f"| `{f.path}` | {f.lineno} | `{types}` | `{f.body_op}` | "
            f"`{f.nearby_context[:60]}` |"
        )
    if not broad_undoc:
        lines.append("| _(none — every hot-path broad except is documented)_ |  |  |  |  |")
    lines.append("")

    lines.extend([
        "## BROAD in hot-path WITH justification (acceptable)",
        "",
        "| File | Line | Handler | Body |",
        "|---|---|---|---|",
    ])
    broad_doc = [f for f in broad_hot if f.documented]
    for f in sorted(broad_doc, key=lambda x: (x.path, x.lineno)):
        types = " / ".join(f.handler_types)
        lines.append(
            f"| `{f.path}` | {f.lineno} | `{types}` | `{f.body_op}` |"
        )
    if not broad_doc:
        lines.append("| _(none)_ |  |  |  |")
    lines.append("")

    lines.extend([
        "## TIGHT in hot-path (specific exception types — usually defensible)",
        "",
        "Each entry handles a specific exception type and silence is "
        "usually intentional (cleanup / parse-failure / try-the-next-"
        "candidate patterns).  Listed for completeness so reviewers "
        "can challenge any individual site.",
        "",
        "| File | Line | Handler | Body |",
        "|---|---|---|---|",
    ])
    for f in sorted(tight_hot, key=lambda x: (x.path, x.lineno)):
        types = " / ".join(f.handler_types)
        lines.append(
            f"| `{f.path}` | {f.lineno} | `{types}` | `{f.body_op}` |"
        )
    if not tight_hot:
        lines.append("| _(none)_ |  |  |  |")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="Emit findings as JSON (for lint scripts).")
    parser.add_argument("--out", default="coord/reviews/silent-exception-audit.md",
                        help="Output markdown path (default: "
                        "coord/reviews/silent-exception-audit.md)")
    args = parser.parse_args()

    findings = scan_repo()
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return 0

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_report(findings), encoding="utf-8")

    broad_undoc = [
        f for f in findings
        if f.classification == "broad" and f.is_hotpath and not f.documented
    ]
    print(f"[audit] wrote {out}", file=sys.stderr)
    print(f"[audit] total={len(findings)} broad_hotpath_undoc={len(broad_undoc)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
