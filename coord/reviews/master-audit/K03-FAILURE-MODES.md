<!-- name=K03-FAILURE-MODES latency_ms=104845 error='' -->

## Score
1. **Correctness — 4** — Top 7 modes (freq×impact): 1) git_clean hard-blocks autonomy (blast: loop off, recovery: `preflight --fix`, TTR 2m), 2) observer probe timeout (blast: daily `[!]` fatigue, recovery: re-run preflight, TTR 1m), 3) dead_engine quarantine silent-fail (blast: dispatch storm, recovery: `engines heal`, TTR 3m), 4) stash-needed dirty tree (blast: auto-block, recovery: `--fix`, TTR 2m), 5) DPAPI/secrets missing (blast: total auth fail, recovery: `env-wizard`, TTR 10m), 6) audit STOP noise (blast: false alarm, recovery: rerun/ignore, TTR 5m), 7) canary false-positive (blast: revert panic, recovery: manual review, TTR 15m). All mapped to CLI verbs except 6/7.
2. **Robustness — 3** — Modes 2 and 6 are chronic flapping warnings with no backoff; mode 3 was a silent schema failure now patched but revealed `except: continue` swallowing.
3. **Operator-usability — 4** — Runbook and `harness today` give non-technical recovery paths for modes 1–5; modes 6–7 still require engineering context to interpret.
4. **Test discipline — 4** — 1576 tests caught mode 3 once surfaced; no automated test for mode 2 observer-timeout race or mode 6 MiMo variance.
5. **Risk — 3** — Modes 2+6 will fire daily; within 30 days the operator will normalize ignoring `[!]` and STOPs, masking a real mode 1/3/5 failure.

6. **Top blocker** — Harden the observer probe with retry/backoff and downgrade its preflight result from `[!]` to soft advisory so mode 2 stops crying wolf.
7. **Verdict** — SHIP-WITH-FIXES — High-frequency failure modes have fast CLI recovery, but daily flapping warnings (modes 2, 6) will erode operator trust before day 30 without a quieter gate.
