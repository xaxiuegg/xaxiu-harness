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
    # Kimi-CLI applies edits in-place inside the cwd it's invoked from.
    # --add-dir tells the CLI which worktree to scope to.
    cmd = [
        "xaxiu-swarm", "dispatch",
        "--backend", backend,
        "--add-dir", str(wt_path),
        "--timeout", "420",
        str(packet_path),
    ]
    cwd_path = str(wt_path)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd_path, capture_output=True, text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return SimpleNamespace(
            success=False, text="", error="xaxiu-swarm not on PATH",
            tokens_used=0, cost_usd=0.0,
        )
    except NotADirectoryError:
        return SimpleNamespace(
            success=False, text="", error=f"worktree not found: {wt_path}",
            tokens_used=0, cost_usd=0.0,
        )
    except subprocess.TimeoutExpired:
        return SimpleNamespace(
            success=False, text="", error="swarm dispatch timeout (600s)",
            tokens_used=0, cost_usd=0.0,
        )
    success = proc.returncode == 0
    return SimpleNamespace(
        success=success,
        text=proc.stdout,  # agentic CLI emits status to stdout; edits land on disk
        error=None if success else (proc.stderr.strip() or f"swarm exit {proc.returncode}"),
        tokens_used=0,
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


def _build_prompt(task_obj, step, read_set_contents: dict[str, str]) -> str:
    """Build a dispatch packet prompt for a single step."""
    lines = [
        f"# Worker Task: {task_obj.worker_id}",
        f"## Step: {step.step_id} ({step.kind})",
        f"\n{step.instruction}\n",
        "## Context Files",
    ]
    for path, content in read_set_contents.items():
        lines.append(f"\n### {path}\n```\n{content}\n```\n")
    lines.append("\n## Instructions")
    lines.append("Apply changes using FILE/REPLACE blocks:")
    lines.append("```")
    lines.append("FILE: relative/path/to/file.py")
    lines.append("<<<<<<< SEARCH")
    lines.append("old text")
    lines.append("=======")
    lines.append("new text")
    lines.append(">>>>>>> REPLACE")
    lines.append("```")
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
    """Apply parsed edits under *base_path*; return list of modified files."""
    modified: list[str] = []
    for rel_path, search, replace in edits:
        file_path = base_path / rel_path
        if not file_path.exists():
            # Create parent dirs if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(replace, encoding="utf-8")
            modified.append(rel_path)
            continue
        content = file_path.read_text(encoding="utf-8")
        if search not in content:
            continue
        new_content = content.replace(search, replace, 1)
        file_path.write_text(new_content, encoding="utf-8")
        modified.append(rel_path)
    return modified


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
    resume_from: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Execute a worker task and produce checkpoint + deliverable."""
    from harness.coord.schemas import WorkerTask
    from harness.engines.dispatcher import dispatch_packet

    task_obj = WorkerTask.model_validate(task) if isinstance(task, dict) else task
    repo = project_root or Path.cwd()
    wt_path = worktree_path(run_dir.name, task_obj.worker_id, repo / WORKTREE_ROOT)

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
    total_cost_usd: float = 0.0

    # Pre-load read_set contents for prompt building
    read_set_contents: dict[str, str] = {}
    for rel_path in task_obj.read_set or []:
        src_file = repo / rel_path
        if src_file.exists():
            read_set_contents[rel_path] = src_file.read_text(encoding="utf-8")

    start_idx = ckpt.last_completed_step_index + 1
    idx = start_idx - 1
    for idx in range(start_idx, len(task_obj.steps)):
        step = task_obj.steps[idx]
        _heartbeat_touch(run_dir, task_obj.worker_id)
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_start", "step_id": step.step_id,
            "kind": step.kind, "idx": idx,
        })

        # Build and dispatch prompt packet for edit steps
        if step.kind == "edit" and step.target_files:
            prompt = _build_prompt(task_obj, step, read_set_contents)
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
                    result = dispatch_packet(
                        project="harness-worker",
                        packet_path=str(packet_path),
                        force_engine=engine,
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
            if result.success and result.text.strip():
                edits = _parse_file_edits(result.text)
                if edits:
                    modified = _apply_file_edits(edits, wt_path)
                    files_modified = list(set(files_modified + modified))
                    # Update read_set contents with modified files
                    for rel_path in modified:
                        mod_file = wt_path / rel_path
                        if mod_file.exists():
                            read_set_contents[rel_path] = mod_file.read_text(encoding="utf-8")

                # Accumulate token + cost telemetry for budget meter
                total_tokens += int(getattr(result, "tokens_used", 0) or 0)
                total_cost_usd += float(getattr(result, "cost_usd", 0.0) or 0.0)

            # Commit step changes
            sha = _git_commit(wt_path, f"[{step.step_id}] {task_obj.title}")
            if sha:
                commit_sha = sha

        # Update checkpoint after each step
        ckpt = ckpt.model_copy(update={
            "last_completed_step_id": step.step_id,
            "last_completed_step_index": idx,
            "files_modified": list(set(files_modified + step.target_files)),
            "commit_sha": commit_sha,
        })
        write_checkpoint(checkpoint_path, ckpt)
        _append_progress(run_dir, task_obj.worker_id, {
            "event": "step_done", "step_id": step.step_id,
            "files_modified": list(ckpt.files_modified or []),
        })
        files_modified = list(ckpt.files_modified)

    tests = _run_pytest(task_obj.test_set, cwd=wt_path)
    final_state = "completed" if tests["failed"] == 0 else "failed"
    ckpt = ckpt.model_copy(update={
        "state": final_state,
        "tests_passed": tests["failed"] == 0,
        "tests_summary": f"{tests['passed']}p/{tests['failed']}f/{tests['skipped']}s",
        "commit_sha": commit_sha,
    })
    write_checkpoint(checkpoint_path, ckpt)
    _append_progress(run_dir, task_obj.worker_id, {
        "event": "worker_done", "state": final_state,
        "tests_passed": tests["failed"] == 0,
    })

    # Record into per-engine budget ledger (best-effort, no fail-loud)
    try:
        from harness.budget import record_dispatch as _budget_record
        _budget_record(
            task_id=run_dir.name,
            engine=engine,
            input_tokens=0,
            output_tokens=total_tokens,
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
        "error_tag": None if final_state == "completed" else "L3.worker.E_TEST_FAILED",
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
