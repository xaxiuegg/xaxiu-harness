<!-- name=M10-STATE-ATOMICITY latency_ms=31648 error='' -->

## Score

| Dim | Score | Justification |
|---|---|---|
| **Correctness** | 2 | W8 schema bug proved EngineHealth writes silently failed for an entire wave; the `except Exception: continue` anti-pattern still lurks in any path that hasn't been individually audited. No proof all JSON/CSV/SQLite writes go through validated models. |
| **Robustness** | 1 | No evidence of atomic write primitives (tmp+rename, SQLite WAL/journal). `kill -9` mid-write of `status.csv` (310 rows) or any `state/*.json` yields partial/truncated files with zero automatic recovery. `StateFileCorruptError` is never mentioned as caught, raised, or tested — it either doesn't exist or is never triggered, meaning corruption is silent. |
| **Operator-usability** | 4 | `preflight --fix` and `engines-heal` give the operator self-service repair; `status_csv writable` check exists. Usable surface is good. |
| **Test discipline** | 2 | 1576 tests but none exercised `kill -9` recovery, corrupt-file simulation, or partial-write rollback. The W8 quarantine bug evaded every test because they tested the happy path, not the failure path. The `except Exception: continue` pattern is untestable by design. |
| **Risk** | 4 | Silent state corruption on process kill is the single highest-impact failure mode in a long-running autonomous loop. Operator trusts the state to make routing/health decisions; if it's stale or truncated, cascading bad dispatches follow. |

## Top blocker

Ship a **`state/_atomic_write.py`** utility that every state path must use: write-to-temp → `fsync` → `os.replace` (POSIX atomic rename) → verify re-read checksum. Retrofit `status.csv`, all `state/*.json`, and `engine_health` writes to go through it. Add a `--corrupt-state` preflight check that detects zero-byte or unparseable files and surfaces a `StateFileCorruptError` with recovery guidance. This single artifact lifts Robustness from 1→3 and Risk from 4→2.

## Verdict

**SHIP-WITH-FIXES.** The W8 schema bug proves silent-write failures are not hypothetical; without atomic write guarantees and corruption detection, the next `kill -9` during an autonomous overnight loop will produce unrecoverable stale state that no preflight or heal command knows to look for.
