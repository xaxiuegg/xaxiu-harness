<!-- name=K07-DEAD-CODE latency_ms=122233 error='' -->

## Score
1. **Correctness** — 2. `preflight --skip-engines` and `today` hard-hang; help strings for `swarm-verify`, `engines-heal`, and `status` are truncated stubs; user-facing descriptions still carry W5/W8 wave-scaffolding tombstones.
2. **Robustness** — 2. No guardrail prevents hung commands; the CLI has sprouted 38+ verbs against a 22-verb contract, signaling ungoverned surface-area bloat.
3. **Operator-usability** — 1. A non-technical operator cannot distinguish live verbs from undead stubs when the help surface is littered with pending-wave labels and critical paths timeout.
4. **Test discipline** — 2. 1576 unit tests missed two CLI hangs; no automated gate rejects stub help text or wave-label leakage into the operator-facing CLI.
5. **Risk** — 4. Undead stubs and hanging commands will crater operator trust; the 38+ verb sprawl vs. the 22-verb target implies nearly half the surface may be scaffolding.

6. **Top blocker** — An integration smoke test that exercises every verb with `--help` and a 5-second dry-run, failing CI on any timeout, truncation, or Wave-N scaffolding in user-facing descriptions.
7. **Verdict** — SHIP-WITH-FIXES: hanging commands and scaffolding-polluted CLI surface are unacceptable ship-blockers for a non-technical operator.
