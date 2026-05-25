### Stance summary

v1.0.0 shipped strong foundations—audit trail, install gating, engine failure visibility—but every new feature still requires touching 4+ files (CLI registration, STATUS.csv, tests, CURRENT_PLAN.md) with zero templating. The Week 2 plan is entirely defensive (backup hygiene, doc sync, dep pinning); none of it compounds. The single biggest velocity gap is that adding a new CLI verb or audit-logged operation is a copy-paste-and-pray ritual, and the solo operator can't safely scaffold their own work items. Build the factory, not more widgets.

### Top 3 rows to ship next (ranked)

**1. W14-SCAFFOLD-COMMAND**
- **Title**: `harness new` generator for CLI verbs, tests, STATUS.csv rows, and panel scripts
- **Estimated effort**: M (4-5h)
- **Why this row, by MY lens**: There are 50+ CLI verbs and adding a new one touches `cli.py`, a test file, `STATUS.csv`, and often `CURRENT_PLAN.md`. That's a 4-file ritual that takes 30-60min even for a skilled dev. A `harness new verb <name>` / `harness new test <name>` / `harness new row <W15-FOO>` scaffolder collapses that to 2 minutes and eliminates the class of bugs from missed wiring (e.g., forgetting to register in `engines list`, forgetting the audit-log hook). This is the template/code-gen move that makes every future row cheaper.
- **Acceptance criteria**:
  - `python -m harness new verb engines-status` generates `cli.py` stub with `@click.command()`, auto-registers in the verb list, generates a matching test file with `runner.invoke()` skeleton, and appends a STATUS.csv row with status=`todo`
  - `python -m harness new test test_foo_bar` generates `tests/test_foo_bar.py` with fixtures for mock dispatch, audit log capture, and tmp_path
  - `python -m harness new row W15-FOO "Some title" --category Production` appends to `coord/STATUS.csv` with correct columns and `status=todo`
  - All generated files pass `python -m pytest` on first run (no syntax errors, no missing imports)
  - 12+ tests covering the generator itself

**2. W14-DISPATCH-RETRY-FALLBACK-PRIMITIVE**
- **Title**: Composable retry/fallback chain as a first-class `dispatch()` option
- **Estimated effort**: M (3-4h)
- **Why this row, by MY lens**: The engine failure summary shows DeepSeek alone hit 209 failures in 168h, MiMo hit 27. The v1.0.0 release gate had to manually retry MiMo mid-panel. Right now every caller that needs resilience (panels, loops, burst) re-implements retry logic. A single `dispatch(..., retry=True, fallback_chain=["deepseek", "mimo"])` parameter turns every future engine-touching feature from "build custom retry with try/except and backoff" to "pass one kwarg." The categorizer from W13-ENGINE-FAILURE-VISIBILITY already exists to drive intelligent retry decisions—wire it in.
- **Acceptance criteria**:
  - `dispatch(prompt, engine="kimi", retry=True, fallback_chain=["deepseek", "mimo"])` attempts kimi, on `terminated`/`api_error` categorization falls to deepseek, then mimo
  - Transient errors (categorizer returns `transient`) get 2 automatic retries on the same engine before escalating to fallback
  - Every attempt + retry + fallback lands its own row in `audit.jsonl` with `retry_attempt` / `fallback_from` / `fallback_to` fields
  - `DispatchResult` gains `engine_actual` (which engine succeeded) + `retries` count + `fallbacks_used` list
  - 20+ tests: happy path, single retry, full fallback chain, all-exhausted, audit rows correct, cost tracking sums correctly

**3. W14-TASK-PIPELINE-MAPPER**
- **Title**: `harness task show W15-FOO` — single command to surface any task's full context
- **Estimated effort**: S (2h)
- **Why this row, by MY lens**: W13-AUDIT-INFRA-W12-PLUS fixed the routing bug, but the operator still has to know whether a task is in `spec/wave-N-plan.md` or `coord/STATUS.csv`, then manually grep for context. A `harness task show <id>` that auto-resolves the source (spec file OR STATUS.csv), shows the row's Notes/Status/Category, links to the audit log entries for that task ID, and shows the latest audit verdict would turn "where is this task" from a 3-file hunt into one command. This is the convention-over-configuration move: one canonical entry point for task introspection, no matter where the data lives.
- **Acceptance criteria**:
  - `python -m harness task show W13-AUDIT-JSONL` resolves to `coord/STATUS.csv`, renders Status/Category/Title/Notes in a formatted block
  - `python -m harness task show W5-RR-REVIEW-THREAD` resolves to `spec/wave-5-plan.md`, renders acceptance criteria
  - If task ID not found anywhere, returns a helpful error listing the sources searched
  - `--audit` flag filters `~/.harness/audit.jsonl` for rows containing the task ID and renders the latest verdict
  - 8+ tests covering CSV route, spec route, missing task, audit integration

### Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

- **CI doc-doc-sync gate**: Catches drift but doesn't compound. The doc-sync-bidirectional tests (`test_docs_mention_all_sdk_fns` + `test_docs_no_future_as_present`) already exist. Adding a third gate for inter-doc consistency is polish that costs 1h and saves 0 future hours per feature.
- **`W13-DISK-PRUNE` + `W13-LOCK-DEPS`**: Pure hygiene. Disk space is not currently blocking anything; dep pinning is reproducibility theater for a solo internal tool running on one machine. Neither row unlocks future shipping speed.
- **`harness commands --did-you-mean`** (Week 3): Nice UX for a solo operator who already knows the 5 verbs they use daily. Zero compound leverage.
- **Hallucination test harness** (Week 3): Interesting research, not velocity infrastructure. Ship it when an actual hallucination causes a real problem, not preemptively.

### Single most important action this week

Ship W14-SCAFFOLD-COMMAND so that every row after it takes 2 minutes to wire instead of 30.

### Confidence in your own recommendation

0.82 — The scaffolding command is high-confidence force-multiplier; the dispatch-retry-primitive confidence drops if the categorizer from W13-ENGINE-FAILURE-VISIBILITY has edge cases that would make the fallback logic flaky (need to verify the `api_error` vs `transient` split is clean in the failure summary data before committing to auto-retry behavior).

### What this lens systematically MISSES

Operational risk — dropping backup-secrets-redaction and dep-pinning to build scaffolding means a leaked API key in a backup tarball sits unfixed for another week while we build developer ergonomics; another lens should sanity-check that tradeoff.