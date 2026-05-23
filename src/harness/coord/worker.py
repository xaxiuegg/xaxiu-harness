"""Worker execution — runs one WorkerTask inside its worktree with checkpointing."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.coord.checkpoint import Checkpoint, read_checkpoint, write_checkpoint, now_iso
from harness.coord.worktree import WORKTREE_ROOT, worktree_path


def _append_progress(run_dir: Path, worker_id: str, event: dict) -> None:
    """Atomically append a progress event to checkpoints/<worker_id>.progress.jsonl.

    Best-effort — never raises (worker steps must not fail on telemetry I/O).
    """
    try:
        progress_path = run_dir / "checkpoints" / f"{worker_id}.progress.jsonl"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": now_iso(), **event}, ensure_ascii=False)
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _dispatch_via_swarm(packet_path: Path, engine: str, wt_path: Path) -> Any:
    """Shell out to xaxiu-swarm for `swarm/*` engines (agentic in-place edits).

    Returns a DispatchResult-shaped namespace so the calling code in
    run_worker treats the result the same as in-process dispatch_packet.

    Discovered as a battle-test gap 2026-05-21: dispatch_packet validates
    force_engine against SUPPORTED_BACKENDS which doesn't include the
    `swarm/*` wrapper identifiers — every real worker run would have
    failed with `unsupported_force_engine` before this fix.

    WIRE-DISPATCH-HARDFAIL (2026-05-22): hard-fails with WorktreeMissing
    (L4) when ``wt_path`` does not exist.  Previously fell back to
    ``cwd=None``, which let Kimi-CLI mutate the main repo by accident if
    the agent ignored its --add-dir directive.  The L4 surface keeps the
    dispatch noisy and recoverable instead of silently corrupting state.
    """
    from types import SimpleNamespace
    from harness.errors import WorktreeMissing

    if not wt_path.exists():
        raise WorktreeMissing(
            f"worktree not found for dispatch: {wt_path}",
            context={"engine": engine, "wt_path": str(wt_path)},
        )

    backend = engine.split("/", 1)[1] if "/" in engine else engine

    # WIRE-SWARM-DIRECT-HTTP (2026-05-22): xaxiu-swarm doesn't know about
    # every harness backend.  For REST-only / in-process engines that the
    # swarm CLI never registered, bypass the subprocess wrapper and call
    # dispatch_packet directly.  Operator-facing identifier
    # (``swarm/mimo`` / ``swarm/mock``) stays uniform across plans +
    # configs even though no swarm CLI is involved under the hood.  The
    # integrating supervisor still parses the returned text for
    # FILE/REPLACE blocks, just like swarm/kimi-api.
    #
    # W5-A 2026-05-22: added ``mock`` so the v2 offline smoke test can
    # drive coord end-to-end via swarm/mock without needing a real
    # xaxiu-swarm backend for mock (MockEngine emits a valid FILE/REPLACE
    # block for mock-out-1.txt).  Pre-W5-A, swarm/mock invoked
    # `xaxiu-swarm dispatch --backend mock` which exited non-zero
    # because no such backend is registered.
    _DIRECT_HTTP_BACKENDS = {"mimo", "mock"}
    if backend in _DIRECT_HTTP_BACKENDS:
        from harness.engines.dispatcher import dispatch_packet
        # W6-A1-4 2026-05-23: worker prompts include the full contents of
        # write_set + read_set files (W6-A1-3) and naming-only references
        # to harness APIs.  The injection scanner's dpapi_direct rule
        # (list_secrets/decrypt_secret/read_secret) fires on legitimate
        # harness source like `dpapi.list_secrets()` in doctor.py.  Mark
        # the dispatch as trusted_source — operator-authored spec +
        # repo-on-disk file content + planner-built prompt is by
        # definition not the cross-engine relay threat the scanner
        # guards against.
        result = dispatch_packet(
            project="harness-worker",
            packet_path=str(packet_path),
            force_engine=backend,
            trusted_source=True,
        )
        # Normalise to the SimpleNamespace shape the rest of run_worker
        # consumes.  dispatch_packet returns a DispatchResult with
        # success/text/error/tokens_used/cost_usd — they match 1:1.
        # W7-WORKER-BUDGET-HOOK 2026-05-23: also pass tokens_in /
        # tokens_out so worker.py can record the budget ledger with
        # the correct in/out split (was hardcoded input_tokens=0).
        return SimpleNamespace(
            success=result.success,
            text=result.text or "",
            error=result.error,
            tokens_used=int(getattr(result, "tokens_used", 0) or 0),
            tokens_in=int(getattr(result, "tokens_in", 0) or 0),
            tokens_out=int(getattr(result, "tokens_out", 0) or 0),
            cost_usd=float(getattr(result, "cost_usd", 0.0) or 0.0),
        )

    # Kimi-CLI applies edits in-place inside the cwd it's invoked from.
    # --add-dir tells the CLI which worktree to scope to.
    #
    # W5-N 2026-05-23: force model selection.  xaxiu-swarm's default model
    # per backend isn't aligned with our memorised production picks:
    #   - swarm/deepseek defaults to v4-pro (slow thinking model that
    #     drifts to prose+markdown ~50% in coord runs).  Force v4-flash
    #     (memory: feedback_default_deepseek_v4_flash).
    # Other backends keep swarm CLI defaults (e.g. kimi -> kimi-for-coding).
    _BACKEND_MODEL_OVERRIDES = {
        "deepseek": "deepseek-v4-flash",
    }
    cmd = [
        "xaxiu-swarm", "dispatch",
        "--backend", backend,
        "--add-dir", str(wt_path),
        "--timeout", "420",
        str(packet_path),
    ]
    if backend in _BACKEND_MODEL_OVERRIDES:
        cmd.extend(["--model", _BACKEND_MODEL_OVERRIDES[backend]])
    cwd_path = str(wt_path)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd_path, capture_output=True, text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return SimpleNamespace(
            success=False, text="", error="xaxiu-swarm not on PATH",
            tokens_used=0, tokens_in=0, tokens_out=0, cost_usd=0.0,
        )
    except NotADirectoryError:
        return SimpleNamespace(
            success=False, text="", error=f"worktree not found: {wt_path}",
            tokens_used=0, tokens_in=0, tokens_out=0, cost_usd=0.0,
        )
    except subprocess.TimeoutExpired:
        return SimpleNamespace(
            success=False, text="", error="swarm dispatch timeout (600s)",
            tokens_used=0, tokens_in=0, tokens_out=0, cost_usd=0.0,
        )
    success = proc.returncode == 0
    # W7-WORKER-BUDGET-HOOK 2026-05-23: the swarm CLI path doesn't surface
    # token counts in its stdout protocol — set both in/out to 0 here.
    # Future improvement would parse xaxiu-swarm's status output for usage.
    return SimpleNamespace(
        success=success,
        text=proc.stdout,  # agentic CLI emits status to stdout; edits land on disk
        error=None if success else (proc.stderr.strip() or f"swarm exit {proc.returncode}"),
        tokens_used=0,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
    )


def _heartbeat_touch(run_dir: Path, worker_id: str) -> None:
    """Update mtime on checkpoints/<wid>.heartbeat sentinel.  Best-effort."""
    try:
        hb_path = run_dir / "checkpoints" / f"{worker_id}.heartbeat"
        hb_path.parent.mkdir(parents=True, exist_ok=True)
        hb_path.touch(exist_ok=True)
        # Force mtime update even if file existed
        import os, time
        now = time.time()
        os.utime(hb_path, (now, now))
    except Exception:
        pass


def _run_pytest(test_set: list[str], cwd: Path, timeout_seconds: int = 300) -> dict[str, Any]:
    """Run pytest on *test_set* and return a summary dict."""
    if not test_set:
        return {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0}
    start = datetime.now(timezone.utc)
    args = ["python", "-m", "pytest"] + list(test_set) + ["-q", "--tb=line"]
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds,
    )
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    passed = failed = skipped = 0
    m = re.search(r"(\d+) passed", proc.stdout)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", proc.stdout)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) skipped", proc.stdout)
    if m:
        skipped = int(m.group(1))
    return {
        "ran": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_seconds": elapsed,
    }


def _build_prompt(
    task_obj, step, read_set_contents: dict[str, str],
    strict_paths: list[str] | None = None,
) -> str:
    """Build a dispatch packet prompt for a single step.

    W5-K 2026-05-22: stronger output-format pinning.  Path 2 v2 caught
    DeepSeek v4-pro emitting prose + a single markdown code block
    (the "new file content") instead of FILE/REPLACE.  When the engine
    drops the protocol, the worker parses 0 edits, W4-A fires.  Adding
    explicit "no prose, no markdown wrappers around the protocol" rules
    + 2 concrete examples reduces that drift.

    W5-S 2026-05-23: auto-inject engine-agnostic memory/*.md content
    at the top of the packet so any engine (MiMo / DeepSeek / Kimi /
    Claude) has the operator's standing decisions, conventions, and
    engine quirks before composing output.  See memory/README.md.

    W5-BB 2026-05-23: when ``strict_paths`` lists operator-declared
    relative paths intersecting this step's ``target_files``, inject
    a "MUST be at exact relative path" callout so the engine doesn't
    exercise judgment on path selection (Phase 3 caught the worker
    deviating to its own preferred dir).
    """
    from harness.memory import format_for_packet as _memory_packet

    lines: list[str] = []
    memory_block = _memory_packet()
    if memory_block:
        lines.append(memory_block)
        lines.append("\n---\n")
    lines.extend([
        f"# Worker Task: {task_obj.worker_id}",
        f"## Step: {step.step_id} ({step.kind})",
        f"\n{step.instruction}\n",
    ])
    # W5-BB strict-path enforcement
    step_targets = set(getattr(step, "target_files", []) or [])
    overlap = [p for p in (strict_paths or []) if p in step_targets]
    if overlap:
        lines.append("\n## STRICT PATHS — operator-declared, MUST follow")
        lines.append("")
        lines.append(
            "The operator has explicitly required that this step produce "
            "files at the following exact relative paths.  Do NOT choose "
            "a different directory, do NOT rename, do NOT add suffixes:"
        )
        lines.append("")
        for p in overlap:
            lines.append(f"  - {p}")
        lines.append("")
        lines.append(
            "Failure to use these exact paths will fail the worker check "
            "post-dispatch."
        )
        lines.append("")
    lines.append("## Context Files")
    for path, content in read_set_contents.items():
        lines.append(f"\n### {path}\n```\n{content}\n```\n")
    lines.append("\n## Output Format — STRICT")
    lines.append("")
    lines.append("Respond with **FILE/REPLACE blocks ONLY**.  No prose, no")
    lines.append("commentary, no markdown code fence wrapping the protocol.")
    lines.append("Each block has this exact shape:")
    lines.append("")
    lines.append("FILE: relative/path/to/file.ext")
    lines.append("<<<<<<< SEARCH")
    lines.append("(exact existing text to replace; leave empty to create file or append)")
    lines.append("=======")
    lines.append("(replacement text)")
    lines.append(">>>>>>> REPLACE")
    lines.append("")
    lines.append("- SEARCH text must be byte-exact (the harness now")
    lines.append("  CRLF-normalises line endings, so LF or CRLF both work,")
    lines.append("  but every other character including whitespace must match).")
    lines.append("- Multiple blocks allowed, one per file edit.")
    lines.append("- Do NOT wrap the FILE/REPLACE block in ``` fences.")
    lines.append("- Do NOT emit any prose before, between, or after the blocks.")
    lines.append("- Do NOT emit the entire new file contents inside a markdown")
    lines.append("  code block — that's the wrong format and will be rejected.")
    return "\n".join(lines)


def _parse_file_edits(text: str) -> list[tuple[str, str, str]]:
    """Parse FILE/REPLACE blocks from engine response.

    Returns list of (relative_path, search_text, replace_text).
    """
    edits: list[tuple[str, str, str]] = []
    # Match FILE: path followed by SEARCH/REPLACE block
    pattern = re.compile(
        r"FILE:\s*(.+?)\n"
        r"<<<<<<<\s*SEARCH\n"
        r"(.*?)"
        r"=======\n"
        r"(.*?)"
        r">>>>>>>\s*REPLACE",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        path = m.group(1).strip()
        search = m.group(2)
        replace = m.group(3)
        # Strip exactly one trailing newline from search/replace to normalize
        if search.endswith("\n"):
            search = search[:-1]
        if replace.endswith("\n"):
            replace = replace[:-1]
        edits.append((path, search, replace))
    return edits


def _apply_file_edits(edits: list[tuple[str, str, str]], base_path: Path) -> list[str]:
    """Apply parsed edits under *base_path*; return list of modified files.

    Edit semantics:
      - File does not exist + non-empty REPLACE → create file with REPLACE content
      - File exists + non-empty SEARCH found in content → replace first occurrence
      - File exists + empty SEARCH → APPEND replace to end of file (engines use
        this idiom when they want to add tests to an existing test file without
        echoing the whole prior content into SEARCH).  Separator newline
        inserted if the existing content doesn't already end with one.
      - File exists + non-empty SEARCH NOT found → skip silently (caller logs
        which files weren't modified via the returned list)
    """
    modified: list[str] = []
    for rel_path, search, replace in edits:
        file_path = base_path / rel_path
        if not file_path.exists():
            # Create parent dirs if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # W5-J 2026-05-22: write_bytes preserves engine's LF.
            # write_text on Windows converts \n -> \r\n by default
            # (universal-newlines), which silently mis-represents the
            # engine's output.
            file_path.write_bytes(replace.encode("utf-8"))
            modified.append(rel_path)
            continue
        # Read in binary first so we can detect line endings before
        # Python's universal-newlines decoding (which silently converts
        # \r\n -> \n).
        raw_bytes = file_path.read_bytes()
        is_crlf = b"\r\n" in raw_bytes
        content = raw_bytes.decode("utf-8")  # keeps \r\n intact
        if not search.strip():
            # Empty SEARCH on existing file → append idiom
            sep = "" if content.endswith("\n") else "\n"
            new_content = content + sep + replace
            file_path.write_bytes(_match_line_endings(new_content, is_crlf))
            modified.append(rel_path)
            continue

        # W5-J 2026-05-22: CRLF-tolerant matching.
        # DeepSeek/Kimi/MiMo all emit \n line endings.  Windows files often
        # have \r\n.  Byte-exact `search in content` then fails even when
        # the engine produced the right text.  Path 2 pilot caught this on
        # CHANGELOG.md (smoking gun: valid FILE/REPLACE block from
        # DeepSeek, but file is CRLF -> silent_no_op).  Strategy:
        #   1. Try byte-exact (preserves existing behaviour)
        #   2. If miss, normalise both to LF and retry — apply replace in
        #      LF space, then re-emit with original line endings
        if search in content:
            new_content = content.replace(search, replace, 1)
        else:
            content_lf = content.replace("\r\n", "\n")
            search_lf = search.replace("\r\n", "\n")
            if search_lf in content_lf:
                replace_lf = replace.replace("\r\n", "\n")
                new_content = content_lf.replace(search_lf, replace_lf, 1)
            else:
                # W5-R 2026-05-23: anchor-fuzzy match.
                # Engines occasionally drop or normalize whitespace +
                # punctuation in SEARCH text (Phase B Pilot G2v2 found
                # DeepSeek emit "def main():" against file content
                # "def main() -> int:").  Last-resort: collapse runs of
                # whitespace + trailing whitespace per line, retry match.
                # Only fires when fuzzy match has EXACTLY ONE candidate
                # to avoid mis-applying.
                fuzzy_result = _fuzzy_replace_one(content_lf, search_lf, replace.replace("\r\n", "\n"))
                if fuzzy_result is None:
                    continue  # truly absent or ambiguous — safe skip
                new_content = fuzzy_result

        file_path.write_bytes(_match_line_endings(new_content, is_crlf))
        modified.append(rel_path)
    return modified


def _collapse_ws(text: str) -> str:
    """Collapse runs of whitespace within each line, then strip per-line trailing.

    Preserves line structure (newlines kept) but drops cosmetic variation
    inside a line (e.g. `def main():` vs `def main() -> int:` would still
    differ, but `foo(a,b)` vs `foo(a, b)` would normalise to the same).
    """
    import re
    out_lines: list[str] = []
    for line in text.split("\n"):
        # Collapse all runs of whitespace to single space + rstrip
        collapsed = re.sub(r"[ \t]+", " ", line).rstrip()
        out_lines.append(collapsed)
    return "\n".join(out_lines)


def _fuzzy_replace_one(content_lf: str, search_lf: str, replace_lf: str) -> str | None:
    """W5-R: whitespace-normalised SEARCH match.

    Args:
        content_lf: file content with LF line endings (already normalized
            by caller).
        search_lf: engine's SEARCH text with LF line endings.
        replace_lf: engine's REPLACE text with LF line endings.

    Returns:
        Modified content with the replacement applied, OR None if no
        unambiguous match found.  None covers two cases:
        - Truly absent: no fuzzy match
        - Ambiguous: 2+ candidate locations (refuse to mis-apply)
    """
    if not search_lf.strip():
        return None
    norm_search = _collapse_ws(search_lf)
    if not norm_search.strip():
        return None

    # Walk content line-by-line, find candidate starts where the search's
    # first non-empty line matches (whitespace-collapsed).
    content_lines = content_lf.split("\n")
    search_lines = norm_search.split("\n")
    search_lines = [l for l in search_lines if l.strip()]
    if not search_lines:
        return None
    first_search = search_lines[0]

    candidates: list[tuple[int, int]] = []  # (start_line, end_line) inclusive
    for start in range(len(content_lines)):
        # Collapse content_lines[start] and compare to first_search
        if _collapse_ws(content_lines[start]) != first_search:
            continue
        # Try to extend match across the remaining search lines
        cur = start
        ok = True
        for sl in search_lines[1:]:
            cur += 1
            # Skip blank lines in content (engine often drops them)
            while cur < len(content_lines) and not content_lines[cur].strip():
                cur += 1
            if cur >= len(content_lines):
                ok = False
                break
            if _collapse_ws(content_lines[cur]) != sl:
                ok = False
                break
        if ok:
            candidates.append((start, cur))

    if len(candidates) != 1:
        return None  # ambiguous or absent — refuse to mis-apply

    start, end = candidates[0]
    # Splice: lines before start, then replace, then lines after end
    before = "\n".join(content_lines[:start])
    after = "\n".join(content_lines[end + 1:])
    parts = []
    if before:
        parts.append(before)
    parts.append(replace_lf.rstrip("\n"))
    if after:
        parts.append(after)
    joined = "\n".join(parts)
    # Preserve trailing newline if original had one
    if content_lf.endswith("\n") and not joined.endswith("\n"):
        joined += "\n"
    return joined


def _detect_inplace_edits(wt_path: Path) -> list[str]:
    """W5-P 2026-05-23: detect files changed in-place by agentic engines.

    Kimi-CLI (xaxiu-swarm --backend kimi) is agentic — it doesn't emit
    FILE/REPLACE blocks, it opens files and edits them directly via
    Edit/Write tools.  Same for any future agentic backend.  This
    function shells out to `git status --porcelain` inside the worktree
    to find files that changed since the worktree was created, returning
    relative paths.

    Operates as a fallback: callers should only invoke this when
    `_parse_file_edits()` returned 0 edits (no FILE/REPLACE protocol
    output).  Universal across all engines — if an agentic engine
    landed edits via tools, this picks them up; if a text engine
    drifted to prose+markdown and made no real edits, this still
    returns [] so W4-A correctly fires.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(wt_path), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []
    modified: list[str] = []
    for line in (proc.stdout or "").splitlines():
        if len(line) < 4:
            continue
        # `git status --porcelain` format: XY <path>
        # X = index, Y = worktree; we want any change.
        path = line[3:].strip()
        # Handle renames "old -> new" by taking the new path
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        # Strip surrounding quotes git uses for paths with spaces
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path:
            modified.append(path)
    return modified


def _match_line_endings(text: str, want_crlf: bool) -> bytes:
    """Re-emit text with the originally-detected line ending convention.

    Avoids smuggling \\n into a CRLF file (and vice versa), which would
    leave the file with mixed line endings on disk.
    """
    if want_crlf:
        # Normalise to LF first so we don't accidentally double-up on
        # already-CRLF chunks, then emit as CRLF.
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.encode("utf-8")


def _git_commit(wt_path: Path, message: str) -> str | None:
    """Stage all changes in *wt_path* and commit; return commit SHA or None."""
    try:
        subprocess.run(
            ["git", "-C", str(wt_path), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(wt_path), "commit", "-m", message, "--no-verify"],
            check=True,
            capture_output=True,
        )
        proc = subprocess.run(
            ["git", "-C", str(wt_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def run_worker(
    task: dict[str, Any],
    run_dir: Path,
    *,
    engine: str = "swarm/kimi",
    fallback_engine: str | None = None,
    resume_from: Path | None = None,
    project_root: Path | None = None,
    strict_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a worker task and produce checkpoint + deliverable.

    W5-O 2026-05-23: ``fallback_engine`` is dispatched as a second
    attempt when the primary returns a response but the FILE/REPLACE
    parse produces 0 edits (engine compliance drift — observed on
    DeepSeek v4-pro and v4-flash ~50% of dispatches).  When MiMo Pro
    + DeepSeek are configured as a pair, the chance both drift on the
    same step approaches zero, removing the "only one engine works"
    constraint from production-readiness.

    W5-BB 2026-05-23: ``strict_paths`` (operator-declared in the spec
    via ``## Strict Paths``) propagates to packet-building so the
    engine sees the path-enforcement callout.  Auto-loaded from
    run_dir/plan.json when not explicitly passed; explicit overrides
    that.  Pre-creates parent directories so the engine just needs to
    write the file.
    """
    from harness.coord.schemas import WorkerTask
    from harness.engines.dispatcher import dispatch_packet

    task_obj = WorkerTask.model_validate(task) if isinstance(task, dict) else task
    repo = project_root or Path.cwd()
    wt_path = worktree_path(run_dir.name, task_obj.worker_id, repo / WORKTREE_ROOT)

    # W5-BB: load strict_paths from plan.json when caller didn't pass them.
    if strict_paths is None:
        plan_path = run_dir / "plan.json"
        if plan_path.exists():
            try:
                import json as _json_for_plan
                plan_data = _json_for_plan.loads(plan_path.read_text(encoding="utf-8"))
                strict_paths = list(plan_data.get("strict_paths") or [])
            except (OSError, ValueError):
                strict_paths = []
        else:
            strict_paths = []
    # Pre-create parent dirs in the worktree so the engine just writes the file.
    for rel in strict_paths or []:
        parent = (wt_path / rel).parent
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    checkpoint_path = run_dir / "checkpoints" / f"{task_obj.worker_id}.json"
    ckpt = read_checkpoint(checkpoint_path) if resume_from is None else read_checkpoint(resume_from)
    if ckpt is None:
        ckpt = Checkpoint(
            worker_id=task_obj.worker_id,
            run_id=run_dir.name,
            state="in_progress",
        )

    started_at = now_iso()
    files_modified: list[str] = list(ckpt.files_modified or [])
    commit_sha = ckpt.commit_sha
    total_tokens: int = 0
    # W7-WORKER-BUDGET-HOOK 2026-05-23: track tokens_in / tokens_out
    # separately so the budget ledger reflects real usage (the prior
    # _budget_record call hardcoded input_tokens=0 because the
    # accumulator didn't split them).
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0

    # Pre-load read_set contents for prompt building
    read_set_contents: dict[str, str] = {}
    for rel_path in task_obj.read_set or []:
        src_file = repo / rel_path
        if src_file.exists():
            read_set_contents[rel_path] = src_file.read_text(encoding="utf-8")
    # W6-A1-3 2026-05-23: also include existing write_set files in the
    # context.  Planners frequently emit read_set=[] when a task writes to
    # an existing file (they think "write" implies "no read needed").  But
    # the engine needs to see the existing content to produce a valid
    # FILE/REPLACE block with matching anchors.  W6-A1 run3 (mimo) failed
    # silent_no_op and run4 (kimi-api) skipped src/harness/doctor.py for
    # exactly this reason — the worker prompt had no view of doctor.py's
    # existing definitions, so the engine couldn't anchor edits.  Skip new
    # files (don't exist on disk yet — they go through the empty-SEARCH
    # create idiom) and skip duplicates already in read_set.
    for rel_path in task_obj.write_set or []:
        if rel_path in read_set_contents:
            continue
        src_file = repo / rel_path
        if src_file.exists():
            read_set_contents[rel_path] = src_file.read_text(encoding="utf-8")

    start_idx = ckpt.last_completed_step_index + 1
    idx = start_idx - 1
    # W5-O 2026-05-23: log primary + fallback engines once at worker start
    # so diagnostics show whether fallback was wired through (vs silently
    # None when CLI plumbing breaks).
    _append_progress(run_dir, task_obj.worker_id, {
        "event": "worker_engines",
        "primary": engine,
        "fallback": fallback_engine,
    })
    for idx in range(start_idx, len(task_obj.steps)):
        step = task_obj.steps[idx]
        _heartbeat_touch(run_dir, task_obj.worker_id)
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_start", "step_id": step.step_id,
            "kind": step.kind, "idx": idx,
        })

        # Build and dispatch prompt packet for edit + create steps.
        # W5-Q 2026-05-23: extended kind matching.  Pre-W5-Q only "edit"
        # triggered dispatch.  Planners emit kind="create" for new-file
        # tasks (Pilot G2 caught this — step s2 was kind=create + new
        # tests/file, worker silently skipped dispatch, file never
        # created, W4-A didn't fire because target_files was new-file
        # placeholder).  "create" semantics: SEARCH is empty + REPLACE
        # is the full file content (same as edit's append idiom).
        if step.kind in ("edit", "create") and step.target_files:
            prompt = _build_prompt(
                task_obj, step, read_set_contents, strict_paths=strict_paths,
            )
            packet_path = repo / "state" / f".tmp_worker_{task_obj.worker_id}_{step.step_id}_{uuid.uuid4().hex}.md"
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            packet_path.write_text(prompt, encoding="utf-8")
            try:
                _heartbeat_touch(run_dir, task_obj.worker_id)
                # Route `swarm/*` engines through the xaxiu-swarm CLI
                # (agentic in-place edits) rather than in-process
                # dispatch_packet (which only knows direct engines).
                # Battle-test finding 2026-05-21: dispatch_packet
                # rejects "swarm/kimi" because SUPPORTED_BACKENDS doesn't
                # include the wrapper-style identifiers.
                if engine.startswith("swarm/"):
                    result = _dispatch_via_swarm(
                        packet_path, engine, wt_path,
                    )
                else:
                    # W6-A1-4 2026-05-23: see _dispatch_via_swarm note —
                    # worker prompts are repo-on-disk + operator-authored
                    # content; trusted_source bypasses the injection
                    # scanner that fires on legit harness code.
                    result = dispatch_packet(
                        project="harness-worker",
                        packet_path=str(packet_path),
                        force_engine=engine,
                        trusted_source=True,
                    )
            except Exception as exc:
                # WIRE-DISPATCH-HARDFAIL (2026-05-22): catch L4 WorktreeMissing
                # (and any other dispatch-time exception) so the worker fails
                # cleanly instead of leaving an orphan checkpoint in
                # in_progress.  The L4 tag is written to a side-channel
                # error file alongside the checkpoint (the Checkpoint schema
                # is closed and adding fields would break readers).
                from harness.errors import HarnessError
                tag = exc.tag() if isinstance(exc, HarnessError) else "L4.dispatch.E_DISPATCH_UNCAUGHT"
                diagnostic = str(exc)[:500]
                ckpt = ckpt.model_copy(update={
                    "state": "failed",
                    "tests_summary": f"dispatch_error:{tag}",
                })
                write_checkpoint(checkpoint_path, ckpt)
                err_path = checkpoint_path.with_suffix(".error.json")
                try:
                    err_path.write_text(json.dumps({
                        "worker_id": task_obj.worker_id,
                        "error_tag": tag,
                        "diagnostic": diagnostic,
                        "at": now_iso(),
                    }, indent=2), encoding="utf-8")
                except OSError:
                    pass
                _append_progress(run_dir, task_obj.worker_id, {
                    "event": "worker_failed",
                    "error_tag": tag,
                    "diagnostic": diagnostic[:200],
                })
                return {
                    "schema_version": 1,
                    "worker_id": task_obj.worker_id,
                    "run_id": run_dir.name,
                    "state": "failed",
                    "started_at": started_at,
                    "finished_at": now_iso(),
                    "steps_completed": [],
                    "files_modified": list(files_modified),
                    "test_summary": {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0},
                    "commit_sha": commit_sha,
                    "error_tag": tag,
                    "diagnostic": diagnostic,
                    "tokens_used": total_tokens,
                    "cost_usd": total_cost_usd,
                    "elapsed_seconds": 0,
                }
            finally:
                packet_path.unlink(missing_ok=True)

            _heartbeat_touch(run_dir, task_obj.worker_id)
            # WIRE-NOOP-DETECT (2026-05-22): track ACTUALLY-modified files per
            # step so we can distinguish "engine returned FILE/REPLACE blocks
            # that matched anchors" from "engine returned junk and zero edits
            # landed".  Without this, target_files (the SPEC's claim of what
            # SHOULD change) was being unconditionally folded into checkpoint
            # files_modified, masking silent no-ops where the worker reports
            # state=completed without shipping anything.
            step_modified: list[str] = []
            engine_used = engine
            if result.success and result.text.strip():
                edits = _parse_file_edits(result.text)
                if edits:
                    step_modified = _apply_file_edits(edits, wt_path)
                else:
                    # W5-P 2026-05-23: no FILE/REPLACE blocks parsed.
                    # The engine might be agentic (Kimi-CLI edits files
                    # in-place via Edit/Write tools — no protocol in the
                    # response text).  Check worktree for actual changes
                    # via git status.  Universal across engines.
                    step_modified = _detect_inplace_edits(wt_path)

                if step_modified:
                    files_modified = list(set(files_modified + step_modified))
                    # Update read_set contents with modified files
                    for rel_path in step_modified:
                        mod_file = wt_path / rel_path
                        if mod_file.exists():
                            read_set_contents[rel_path] = mod_file.read_text(encoding="utf-8")

            # W5-O 2026-05-23: engine fallback.
            # If primary engine produced 0 applicable edits — whether
            # because it drifted (success=True but bad protocol) or
            # because it failed outright (success=False, network/crash)
            # — retry with fallback_engine.  Removes the "only one engine
            # works" production-readiness constraint.  Skipped only when
            # primary already produced edits OR no fallback is configured.
            #
            # Fix iteration (Pilot F): originally gated on
            # `result.success and result.text.strip()` which skipped
            # fallback when primary failed outright.  Kimi-CLI sometimes
            # exits non-zero before producing FILE/REPLACE — that's
            # exactly when fallback should rescue the run.
            if (not step_modified
                    and fallback_engine
                    and fallback_engine != engine):
                # W6-A1.2 2026-05-23: emit progress events for every
                # fallback attempt so operators can verify the W5-O
                # rescue chain is actually firing (not silently
                # skipping).  Closes the observability gap surfaced
                # in W6-A1's silent-fallback investigation.
                _append_progress(run_dir, task_obj.worker_id, {
                    "event": "fallback_attempted",
                    "step_id": step.step_id,
                    "primary_engine": engine,
                    "fallback_engine": fallback_engine,
                    "reason": "primary produced 0 edits",
                })
                _heartbeat_touch(run_dir, task_obj.worker_id)
                fb_packet_path = repo / "state" / (
                    f".tmp_worker_{task_obj.worker_id}_{step.step_id}_fb_"
                    f"{uuid.uuid4().hex}.md"
                )
                fb_packet_path.parent.mkdir(parents=True, exist_ok=True)
                fb_packet_path.write_text(prompt, encoding="utf-8")
                try:
                    if fallback_engine.startswith("swarm/"):
                        fb_result = _dispatch_via_swarm(
                            fb_packet_path, fallback_engine, wt_path,
                        )
                    else:
                        # W6-A1-4 2026-05-23: trusted_source — same rationale
                        # as the primary dispatch call above.
                        fb_result = dispatch_packet(
                            project="harness-worker",
                            packet_path=str(fb_packet_path),
                            force_engine=fallback_engine,
                            trusted_source=True,
                        )
                    fb_success = bool(fb_result.success)
                    fb_text_len = len((fb_result.text or "").strip())
                    _append_progress(run_dir, task_obj.worker_id, {
                        "event": "fallback_dispatch_result",
                        "step_id": step.step_id,
                        "fallback_engine": fallback_engine,
                        "success": fb_success,
                        "text_len": fb_text_len,
                        "error": getattr(fb_result, "error", None),
                    })
                    if fb_success and fb_text_len > 0:
                        fb_edits = _parse_file_edits(fb_result.text)
                        if fb_edits:
                            step_modified = _apply_file_edits(fb_edits, wt_path)
                        else:
                            # W5-P fallback path: agentic engine may have
                            # edited in-place via tools.  Check worktree.
                            step_modified = _detect_inplace_edits(wt_path)
                    else:
                        # Even on fallback dispatch failure, check
                        # worktree — agentic engines may have applied
                        # edits before the failure.
                        step_modified = _detect_inplace_edits(wt_path)
                    _append_progress(run_dir, task_obj.worker_id, {
                        "event": "fallback_edits_applied",
                        "step_id": step.step_id,
                        "fallback_engine": fallback_engine,
                        "edits_applied": len(step_modified or []),
                        "files": list(step_modified or []),
                    })
                    if step_modified:
                        engine_used = fallback_engine
                        files_modified = list(set(
                            files_modified + step_modified
                        ))
                        for rel_path in step_modified:
                            mod_file = wt_path / rel_path
                            if mod_file.exists():
                                read_set_contents[rel_path] = (
                                    mod_file.read_text(encoding="utf-8")
                                )
                except Exception as fb_exc:
                    # W6-A1.2: log the exception too so silent failures
                    # in the fallback path don't hide the real cause.
                    _append_progress(run_dir, task_obj.worker_id, {
                        "event": "fallback_exception",
                        "step_id": step.step_id,
                        "fallback_engine": fallback_engine,
                        "exception": f"{type(fb_exc).__name__}: {fb_exc}",
                    })
                    # fallback is best-effort; primary's W4-A guard still fires
                finally:
                    fb_packet_path.unlink(missing_ok=True)
            _append_progress(run_dir, task_obj.worker_id, {
                "event": "step_engine_used", "step_id": step.step_id,
                "engine_used": engine_used,
            })

            # Accumulate token + cost telemetry for budget meter
            if result.success and result.text.strip():
                total_tokens += int(getattr(result, "tokens_used", 0) or 0)
                # W7-WORKER-BUDGET-HOOK: split accumulator.  Engines
                # that don't surface a split (swarm CLI path) report
                # tokens_in=tokens_out=0 here — that's truthful
                # ("we don't know") instead of attributing everything
                # to output as the old single-accumulator did.
                total_tokens_in += int(getattr(result, "tokens_in", 0) or 0)
                total_tokens_out += int(getattr(result, "tokens_out", 0) or 0)
                total_cost_usd += float(getattr(result, "cost_usd", 0.0) or 0.0)

            # WIRE-NOOP-DETECT: if this is an edit step with target_files,
            # we EXPECTED edits.  Zero actual edits → engine failure mode.
            # Fail the worker loud rather than silently claiming completion.
            if step.kind in ("edit", "create") and step.target_files and not step_modified:
                diagnostic = (
                    f"silent_no_op: step {step.step_id} declared "
                    f"target_files={list(step.target_files)} but 0 files were "
                    f"modified.  Engine likely returned non-matching anchors "
                    f"or no FILE/REPLACE blocks.  result.success={result.success}, "
                    f"text_len={len(result.text or '')}."
                )
                ckpt = ckpt.model_copy(update={
                    "state": "failed",
                    "tests_summary": f"silent_no_op:{step.step_id}",
                })
                write_checkpoint(checkpoint_path, ckpt)
                err_path = checkpoint_path.with_suffix(".error.json")
                try:
                    err_path.write_text(json.dumps({
                        "worker_id": task_obj.worker_id,
                        "error_tag": "L3.dispatch.E_SILENT_NO_OP",
                        "diagnostic": diagnostic,
                        "at": now_iso(),
                    }, indent=2), encoding="utf-8")
                except OSError:
                    pass
                _append_progress(run_dir, task_obj.worker_id, {
                    "event": "worker_failed",
                    "error_tag": "L3.dispatch.E_SILENT_NO_OP",
                    "diagnostic": diagnostic[:200],
                })
                return {
                    "schema_version": 1,
                    "worker_id": task_obj.worker_id,
                    "run_id": run_dir.name,
                    "state": "failed",
                    "started_at": started_at,
                    "finished_at": now_iso(),
                    "steps_completed": [],
                    "files_modified": [],
                    "test_summary": {"ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0},
                    "commit_sha": commit_sha,
                    "error_tag": "L3.dispatch.E_SILENT_NO_OP",
                    "diagnostic": diagnostic,
                    "tokens_used": total_tokens,
                    "cost_usd": total_cost_usd,
                    "elapsed_seconds": 0,
                }

            # Commit step changes
            sha = _git_commit(wt_path, f"[{step.step_id}] {task_obj.title}")
            if sha:
                commit_sha = sha

        # Update checkpoint after each step.
        # WIRE-NOOP-DETECT: files_modified now reflects ACTUAL applied edits
        # (step_modified) accumulated into files_modified above, not the spec's
        # intended scope (step.target_files).
        ckpt = ckpt.model_copy(update={
            "last_completed_step_id": step.step_id,
            "last_completed_step_index": idx,
            "files_modified": list(files_modified),
            "commit_sha": commit_sha,
        })
        write_checkpoint(checkpoint_path, ckpt)
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_done", "step_id": step.step_id,
            "files_modified": list(ckpt.files_modified or []),
        })
        files_modified = list(ckpt.files_modified)

    tests = _run_pytest(task_obj.test_set, cwd=wt_path)
    # W5-BB 2026-05-23: post-validate strict_paths exist in the worktree.
    # Missing paths flip final_state to failed + emit a structured progress
    # event so the operator sees exactly which path the worker dropped.
    strict_missing: list[str] = []
    for rel in strict_paths or []:
        if not (wt_path / rel).exists():
            strict_missing.append(rel)
    if strict_missing:
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "strict_paths_violation",
            "missing": strict_missing,
            "declared": list(strict_paths or []),
        })
    tests_ok = tests["failed"] == 0 and not strict_missing
    final_state = "completed" if tests_ok else "failed"
    ckpt = ckpt.model_copy(update={
        "state": final_state,
        "tests_passed": tests_ok,
        "tests_summary": f"{tests['passed']}p/{tests['failed']}f/{tests['skipped']}s",
        "commit_sha": commit_sha,
    })
    write_checkpoint(checkpoint_path, ckpt)
    _append_progress(run_dir, task_obj.worker_id, {
        "event": "worker_done", "state": final_state,
        "tests_passed": tests_ok,
    })

    # Record into per-engine budget ledger (best-effort, no fail-loud).
    # W7-WORKER-BUDGET-HOOK 2026-05-23: thread the real tokens_in /
    # tokens_out split instead of the prior input_tokens=0 hardcode.
    # When the underlying engine path can't surface a split (swarm
    # CLI), both accumulators stay at 0 and we fall back to the legacy
    # aggregate via the output_tokens slot for backward compatibility
    # with operators relying on `harness budget summary` totals.
    try:
        from harness.budget import record_dispatch as _budget_record
        if total_tokens_in == 0 and total_tokens_out == 0 and total_tokens > 0:
            # Engines that don't split (swarm CLI) — preserve the
            # legacy "everything to output" behaviour so totals don't
            # silently drop.
            input_tokens_to_record = 0
            output_tokens_to_record = total_tokens
        else:
            input_tokens_to_record = total_tokens_in
            output_tokens_to_record = total_tokens_out
        _budget_record(
            task_id=run_dir.name,
            engine=engine,
            input_tokens=input_tokens_to_record,
            output_tokens=output_tokens_to_record,
        )
    except Exception:
        pass  # ledger best-effort — never fail a worker for budget I/O

    steps_completed = [s.step_id for s in task_obj.steps[:idx + 1]] if task_obj.steps else []
    result: dict[str, Any] = {
        "schema_version": 1,
        "worker_id": task_obj.worker_id,
        "run_id": run_dir.name,
        "state": final_state,
        "started_at": started_at,
        "finished_at": now_iso(),
        "steps_completed": steps_completed,
        "files_modified": files_modified,
        "test_summary": tests,
        "commit_sha": commit_sha,
        "error_tag": (
            None if final_state == "completed"
            else ("L3.worker.E_STRICT_PATH_MISSING" if strict_missing
                  else "L3.worker.E_TEST_FAILED")
        ),
        "diagnostic": "",
        "tokens_used": total_tokens,
        "cost_usd": total_cost_usd,
        "elapsed_seconds": int((datetime.now(timezone.utc) -
                                datetime.fromisoformat(started_at)).total_seconds()),
    }
    deliv_dir = run_dir / "deliverables"
    deliv_dir.mkdir(parents=True, exist_ok=True)
    (deliv_dir / f"{task_obj.worker_id}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
