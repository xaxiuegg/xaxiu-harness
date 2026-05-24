<!-- name=K07-DEAD-CODE latency_ms=183679 error='' -->

## Score

1. **Correctness — 2/5** At least 8 of ~37 visible verbs carry wave-ID scaffolding, `start` is a naked stub, and `today` is live yet absent from `--help`, so the manifest is materially false.

2. **Robustness — 2/5** Ghost verbs (`today`) and duplicate aliases (`engines-heal` / `engines heal`) create bifurcated paths; stubs fail silently or opaquely under operator use.

3. **Operator-usability — 2/5** A non-technical operator depends on `--help`; ticket-number descriptions and missing entries force runbook dependency for basic discovery.

4. **Test discipline — 2/5** 1576 tests guard logic but none appear to assert CLI-tree completeness or stub absence, allowing dead surface code to persist.

5. **Risk — 3/5** Scaffolding debt will confuse incident response and erode trust as the operator discovers unlisted verbs and stubs; fix before next wave.

6. **Top blocker** — One CLI-hygiene commit: strip wave IDs from all `--help` strings, delete or implement the `start` stub, and register `today` / `status human` in the top-level Click group so `--help` becomes a truthful manifest.

7. **Verdict** — SHIP-WITH-FIXES. The harness works, but its CLI surface is still a construction site; the operator cannot trust the verb tree they see.
