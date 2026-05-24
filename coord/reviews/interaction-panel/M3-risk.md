<!-- name=M3-risk latency_ms=22289 error='' -->

**1. Next-best move**  
Harden W7-B1-RETROFIT (`engine/transports.py`). The StreamingTransport ABC is now the path for DeepSeek and Kimi streaming, but MiMo is excluded (batch HTTP). Any ABC break (e.g., `consume_sse` timeout mismatch, missing `reasoning_only` propagation) will silently kill two engines. A targeted wave—`W8-TRANSPORT-REDUNDANCY`—should add: (a) negative-path tests for SSE drops mid-stream, (b) a fallback to batch-HTTP on streaming failure, (c) a transport health-check dashboard line in STATUS.csv.

**2. Interaction patterns**  
**Working:** The operator’s “audit STOPs with honest reporting” loop is gold. It forces real quality gates and prevents spec-shaping.  
**Not working:** The stop-hook noise from STATUS.csv mtime churn. It burns turns and masks real signals. Replace with a `--ignore-mtime-for-mutation` flag that suppresses hook fires when only known mutation-kill-rate files change.

**3. Next 2-3 waves theme**  
**Theme: Observability + Engine-Layer Consolidation.**  
Wave 8 should unify engine transports under a single resilience wrapper (retry, fallback, health reporting). Wave 9 should turn the MiMo auditor into a first-class operator surface: a live dashboard of audit-STOP history, mutation-kill trends, and transport health. Wave 10 should add a lightweight CI layer that runs the full mutation suite + transport smoke tests on every commit, ensuring the hardening sticks as new features land.
