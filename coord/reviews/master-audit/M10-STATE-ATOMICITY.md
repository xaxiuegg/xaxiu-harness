<!-- name=M10-STATE-ATOMICITY latency_ms=20438 error='' -->

## Score

**Correctness**: 2/5 — Quarantine writes to `engine_health` silently failed *every time* until W8; Pydantic rejected `quarantined` status and `except Exception: continue` swallowed it. State files told lies.

**Robustness**: 1/5 — No evidence of atomic writes (temp+rename), no WAL for sqlite, no `StateFileCorruptError` anywhere, and the one observed failure mode was *silent data loss*. `kill -9` mid-write is an open question with no documented mitigation.

**Operator-usability**: 3/5 — Preflight `--fix` and `engines-heal` give the operator recovery verbs, but if those verbs *themselves* silently corrupt state (as the schema bug proved), the UX is a trap.

**Test discipline**: 2/5 — The schema bug survived through W7 *and* was reproduced by the audit tooling — tests never caught a rejected Pydantic write to engine_health. No crash-recovery / mid-write tests visible.

**Risk**: 4/5 — State is the single source of truth for engine routing, quarantine, and cooldown. Silent write failure = operator thinks engine is quarantined, harness keeps dispatching to it. Next outage is load-bearing.

## Top blocker

Add `state/atomic.py` — a write helper that: (a) writes to `.tmp` then `os.replace`, (b) wraps all JSON/SQLite writes, (c) raises `StateFileCorruptError` on any serialization failure instead of swallowing. Then add a kill-during-write integration test. This single artifact closes the atomicity gap and makes the `except Exception: continue` class of bug structurally impossible.

## Verdict

**HOLD** for state write atomicity — the W8 proof that *every quarantine write silently failed* is a ship-blocker until the state layer has crash-safe writes and surface-on-failure error handling.
