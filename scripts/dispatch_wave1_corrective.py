"""Corrective parallel dispatch of the 4 remaining wave1-*.md specs.

Runs the dev-manager role properly: builds 4 packets from operator-authored
spec markdowns, dispatches them in parallel to 4 different engines, captures
each engine's full response to disk for review.  Apply step is manual (done
by Claude as merge step in the next turn).

Operator-authored ingress, so `trusted_source=True` on every dispatch.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.dispatcher import dispatch_packet  # noqa: E402


# ---------------------------------------------------------------------------
# Pack definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pack:
    pack_id: str
    spec_path: str
    engine: str             # primary
    fallback_engine: str    # used on failure


PACKS: list[Pack] = [
    Pack(pack_id="A", spec_path="spec/samples/wave1-coord-status-json.md",
         engine="mimo", fallback_engine="kimi"),
    Pack(pack_id="B", spec_path="spec/samples/wave1-budget-since-days.md",
         engine="mimo", fallback_engine="deepseek"),
    Pack(pack_id="C", spec_path="spec/samples/wave1-session-ok-to-stop-json.md",
         engine="deepseek", fallback_engine="mimo"),
    Pack(pack_id="D", spec_path="spec/samples/wave1-observer-cycle-dry-run.md",
         engine="kimi", fallback_engine="deepseek"),
]


# ---------------------------------------------------------------------------
# Packet shape
# ---------------------------------------------------------------------------

_OUTPUT_INSTRUCTIONS = """\
# Output rules (read first)

- Output **markdown only**. **No tool calls**, no function syntax, no ellipsis.
- Anchors MUST be byte-exact against the read-set files quoted below.
  Do NOT invent the surrounding code — copy from the read-set sections.
- For every file you need to edit, emit a `FILE: <relative/path>` line
  followed by one or more byte-exact FIND/REPLACE blocks:

  ```
  FILE: src/harness/cli.py
  <<<<<<< SEARCH
  <existing exact text, byte-for-byte from the read-set below>
  =======
  <new replacement text>
  >>>>>>> REPLACE
  ```

- For NEW files, emit a FIND block with empty SEARCH and the full content
  in REPLACE (same fence shape).
- For tests, follow the SAME FILE / FIND-REPLACE format — do NOT just
  describe what the test should do.
- No reasoning preamble.  Start directly at the first `FILE:` line.
- Do NOT modify files outside the spec's stated `File scope`.
"""


# Read-set per pack — files quoted into the prompt for byte-exact anchors.
# Keys are spec_path; values are list of repo-relative file paths to embed.
READ_SETS: dict[str, list[str]] = {
    "spec/samples/wave1-coord-status-json.md": [
        "src/harness/cli.py",
        "tests/test_coord_cli.py",
    ],
    "spec/samples/wave1-budget-since-days.md": [
        "src/harness/cli.py",
        "tests/test_budget.py",
    ],
    "spec/samples/wave1-session-ok-to-stop-json.md": [
        "src/harness/cli.py",
        "src/harness/session/stop_check.py",
    ],
    "spec/samples/wave1-observer-cycle-dry-run.md": [
        "src/harness/observer/cycle.py",
        "src/harness/cli.py",
    ],
}

# Big files — embed only the relevant section.  For cli.py (~2000 lines)
# we trim to the relevant click command function ± 40 lines of context.
# Spec-driven anchors: per-pack the anchor string identifies the function
# to extract.
CLI_ANCHORS: dict[str, str] = {
    "spec/samples/wave1-coord-status-json.md":       "def coord_status",
    "spec/samples/wave1-budget-since-days.md":       "def budget_summary",
    "spec/samples/wave1-session-ok-to-stop-json.md": "def session_ok_to_stop",
    "spec/samples/wave1-observer-cycle-dry-run.md":  "def observer_cycle",
}


def _extract_relevant_section(file_text: str, anchor: str | None,
                              window_before: int = 40,
                              window_after: int = 120) -> str:
    """Return ±window lines around the anchor.  Whole file if anchor None or absent."""
    if not anchor:
        return file_text
    lines = file_text.splitlines()
    idx = next((i for i, ln in enumerate(lines) if anchor in ln), -1)
    if idx < 0:
        # Anchor not found — return whole file (better safe than missing)
        return file_text
    start = max(0, idx - window_before)
    end = min(len(lines), idx + window_after)
    head = "" if start == 0 else f"# ... ({start} lines omitted before)\n"
    tail = "" if end == len(lines) else f"# ... ({len(lines) - end} lines omitted after)\n"
    return head + "\n".join(lines[start:end]) + "\n" + tail


def _build_packet(spec_path: Path) -> str:
    spec_text = spec_path.read_text(encoding="utf-8")
    rs_files = READ_SETS.get(str(spec_path).replace("\\", "/"), [])
    cli_anchor = CLI_ANCHORS.get(str(spec_path).replace("\\", "/"))

    parts: list[str] = [_OUTPUT_INSTRUCTIONS, "", "# Spec to implement", "", spec_text]

    if rs_files:
        parts.append("\n# Read-set — byte-exact current contents (use these as your SEARCH anchors)\n")
        for rel in rs_files:
            p = Path(rel)
            if not p.exists():
                parts.append(f"\n## {rel}\n\n(file does not yet exist; create it)\n")
                continue
            text = p.read_text(encoding="utf-8")
            # Trim cli.py to the relevant click command
            if rel.endswith("/cli.py") or rel.endswith("\\cli.py"):
                text = _extract_relevant_section(text, cli_anchor)
            parts.append(f"\n## {rel}\n\n```python\n{text}\n```\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Dispatch one pack (with primary→fallback fallback)
# ---------------------------------------------------------------------------

@dataclass
class PackResult:
    pack_id: str
    spec_path: str
    engine_used: str
    success: bool
    latency_ms: int
    response_text: str
    error: str | None
    response_path: str


def _dispatch_pack(pack: Pack, out_dir: Path) -> PackResult:
    spec_path = Path(pack.spec_path)
    packet_text = _build_packet(spec_path)
    started = time.monotonic()

    fd, tmp_packet = tempfile.mkstemp(suffix=".md", text=True)
    Path(tmp_packet).write_text(packet_text, encoding="utf-8")
    os.close(fd)

    last_error: str | None = None
    used_engine: str = pack.engine
    text: str = ""
    success = False
    try:
        for engine_attempt in (pack.engine, pack.fallback_engine):
            try:
                result = dispatch_packet(
                    project="harness-planner",  # has an adapter
                    packet_path=tmp_packet,
                    force_engine=engine_attempt,
                    trusted_source=True,
                )
            except Exception as exc:
                last_error = f"dispatch_exc[{engine_attempt}]: {exc}"
                continue
            if result.success and (result.text or "").strip():
                used_engine = engine_attempt
                text = result.text
                success = True
                break
            last_error = f"[{engine_attempt}] {result.error or 'empty_response'}"
    finally:
        Path(tmp_packet).unlink(missing_ok=True)

    latency_ms = int((time.monotonic() - started) * 1000)

    # Write response to disk
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}_pack_{pack.pack_id}_{used_engine}.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    header = (
        f"<!-- pack={pack.pack_id} spec={pack.spec_path} engine={used_engine} "
        f"success={success} latency_ms={latency_ms} -->\n"
    )
    out_path.write_text(header + (text if success else f"FAILED\n\n{last_error}\n"),
                        encoding="utf-8")

    return PackResult(
        pack_id=pack.pack_id, spec_path=pack.spec_path,
        engine_used=used_engine if success else f"{pack.engine}+{pack.fallback_engine}",
        success=success, latency_ms=latency_ms,
        response_text=text, error=last_error if not success else None,
        response_path=str(out_path),
    )


# ---------------------------------------------------------------------------
# Orchestrate fan-out
# ---------------------------------------------------------------------------

def main() -> int:
    out_dir = Path("coord/dispatches")
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-workers", type=int, default=2,
                        help="Concurrency cap (default 2 to avoid Kimi rate-limit under fan-out)")
    parser.add_argument("--only", type=str, default=None,
                        help="Run only these packs (comma-separated, e.g. 'A,C').")
    args = parser.parse_args()

    packs = PACKS
    if args.only:
        wanted = {x.strip().upper() for x in args.only.split(",")}
        packs = [p for p in PACKS if p.pack_id in wanted]

    print(f"[dispatch] {len(packs)} packs, max_workers={args.max_workers} "
          f"engines={[p.engine for p in packs]}", flush=True)
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(_dispatch_pack, p, out_dir): p for p in packs}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    elapsed = time.monotonic() - started

    # Order by pack_id for stable reporting
    results.sort(key=lambda r: r.pack_id)
    print(f"\n[dispatch] {elapsed:.1f}s wall total\n")
    print(f"{'pack':5s} {'engine':14s} {'ok':>4s} {'ms':>9s}  response")
    for r in results:
        ok = "✓" if r.success else "✗"
        print(f"{r.pack_id:5s} {r.engine_used:14s} {ok:>4s} {r.latency_ms:>9d}  {r.response_path}")
        if not r.success and r.error:
            print(f"  error: {r.error}")

    # Persist run-level manifest
    manifest_path = out_dir / f"manifest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    manifest_path.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(elapsed, 1),
        "results": [
            {k: v for k, v in asdict(r).items() if k != "response_text"}
            for r in results
        ],
    }, indent=2), encoding="utf-8")
    print(f"\n[dispatch] manifest: {manifest_path}")

    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
