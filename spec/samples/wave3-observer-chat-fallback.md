# wave3-observer-chat-fallback — graceful fallback for audit-chat transcript lookup

## Context

`harness observer audit-chat` errors with `could not locate session
transcript jsonl` when invoked from a project directory that has no
recorded Claude Code sessions yet (typical right after a project-folder
migration: the new cwd's slug dir exists with `memory/` but no jsonl
files have been written there).

Current `_latest_session_jsonl()` in `src/harness/observer/chat.py`:

```python
def _cwd_slug() -> str:
    cwd = str(Path.cwd().resolve())
    return cwd.replace(":", "").replace("\\", "-").replace("/", "-")

def _claude_projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"

def _latest_session_jsonl() -> Optional[Path]:
    base = _claude_projects_dir() / _cwd_slug()
    if not base.exists():
        return None
    candidates = sorted(base.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None
```

When the cwd-slug dir has no jsonl files (newly-created project), audit-chat
fails.  The right behaviour: **search across ALL project dirs**, pick the
most-recently-modified jsonl globally as the "active session".  That way a
session running in any cwd can be audited from any cwd.

## Goal

Update `_latest_session_jsonl()` to fall back to cross-project-dir search
when the cwd-slug dir has no jsonl files.  Order of precedence:

1. cwd-slug dir contains jsonl(s) → newest one (existing behaviour preserved)
2. otherwise → newest jsonl across ALL `~/.claude/projects/*/` dirs (global fallback)
3. otherwise → None (no transcript anywhere; audit returns empty report)

## Acceptance

- Existing `tests/test_observer.py` continues to pass.
- New test `test_latest_session_jsonl_falls_back_globally` covers the
  case where the cwd-slug dir has no jsonl but another project dir does.
- New test `test_latest_session_jsonl_returns_none_when_no_jsonl_anywhere`
  covers the empty case.
- `harness observer audit-chat` no longer raises when called from a
  project dir with no prior session — returns the empty AuditReport.

## File scope

- `src/harness/observer/chat.py` — modify `_latest_session_jsonl()` only.
  Keep new code under 25 LOC.
- `tests/test_observer.py` — append the 2 tests.

## Read-set — byte-exact current contents (use these as your SEARCH anchors)

### src/harness/observer/chat.py (relevant section)

```python
def _cwd_slug() -> str:
    """Return the Claude Code projects-dir slug for the current cwd.

    Claude Code maps a project dir to `~/.claude/projects/<slug>/` where
    <slug> is the absolute path with separators replaced by '-' and the
    drive colon removed.  e.g. D:\\Projects\\xaxiu-harness -> D--Projects-xaxiu-harness
    """
    cwd = str(Path.cwd().resolve())
    return cwd.replace(":", "").replace("\\", "-").replace("/", "-")


def _claude_projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _latest_session_jsonl() -> Optional[Path]:
    base = _claude_projects_dir() / _cwd_slug()
    if not base.exists():
        return None
    candidates = sorted(base.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None
```

DO NOT modify `audit()`, `ChatFlag`, `AuditReport`, or `_cwd_slug`.
Stdlib + existing harness internals only.
