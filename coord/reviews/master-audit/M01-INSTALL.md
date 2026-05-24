<!-- name=M01-INSTALL latency_ms=22414 error='' -->

## Score

1. **Correctness (3/5)**: Preflight timed out with `--skip-engines` on Windows — the exact cold-start gate the fresh-install reviewer needs is non-functional at HEAD. Schema bug was real and fixed, but the timeout means we can't confirm the fix works for a new operator.
2. **Robustness (2/5)**: Two commands timed out (preflight, today). `--fix` silently stashed work (W9-PREFLIGHT-FIX-NOSTASH). CRLF false-positive on the commit hook blocks Windows operators. The Python Foundation Store path in the timeout trace signals PATH/install issues the runbook doesn't cover.
3. **Operator-usability (2/5)**: The `--help` tree has 40+ CLI verbs with flags like `--explore-on-uncertainty [dispatch_alternatives|inline|ask_operator]`. No mention of Python install, venv, or `pip install -e .` anywhere in the snapshot. The operator runbook assumes harness is already running — the gap from "cloned repo" to "preflight green" is undocumented.
4. **Test discipline (4/5)**: 1576 tests, mutation kill rates above gate, 32 new tests in W8. The schema bug slipped through *tests* but was caught by audit. Strong regression signal.
5. **Risk (4/5)**: A fresh-install reviewer literally cannot complete their task. The preflight timeout means the cold-start path is broken, and there's zero evidence of install/bootstrap documentation.

6. **Top blocker**: A `harness bootstrap` or `preflight` that actually succeeds — the Windows timeout trace (`PythonSoftwareFoundation.Python.3.13`) suggests the shebang/module invocation path is broken on Windows Store Python. Either fix the invocation (use `python -m harness` directly from documented entrypoint) or add a one-line install script (`pip install -e . && harness preflight`). The runbook must start at `git clone`, not at "run harness."

7. **Verdict**: **HOLD.** The cold-start gate (`preflight --skip-engines`) times out on Windows — no fresh-install reviewer can validate anything until that path works end-to-end in <30 seconds.
