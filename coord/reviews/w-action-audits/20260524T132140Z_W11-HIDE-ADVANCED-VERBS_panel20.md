# 20-agent audit panel — W11-HIDE-ADVANCED-VERBS (20c98400d8c1)

<!-- engine=20-panel task=W11-HIDE-ADVANCED-VERBS sha=20c98400d8c1 mean_confidence=0.601 verdict=STOP -->

- **Verdict**: STOP
- Mean confidence: 0.601
- Personas passing (≥0.7): 9 / 18 (of 20 dispatched)
- Personas stopping (<0.7): 9
- Elapsed: 185.9s

## Per-persona verdicts

| Persona | Engine | Conf | Verdict | Lens finding |
|---|---|---|---|---|
| K01-correctness | kimi | 0.20 | STOP | The commit hides 13 verbs at the top level via hidden=True and adds an `advanced |
| K02-test-quality | kimi | 0.55 | PASS | Tests verify hidden=True flags and --help omission but rely on weak >=5/13 asser |
| K03-api-surface | kimi | 0.30 | STOP | The `advanced` group only exposes a `list` subcommand and does not actually host |
| K04-error-handling | kimi | 0.30 | STOP | Commit introduces a new file-read in `run_mutation_canary.py` (`module_path.read |
| K05-backwards-compat | kimi | 0.88 | PASS | All 13 engineering verbs remain top-level callable commands (hidden=True only su |
| K06-documentation | kimi | 0.40 | STOP | Docstrings match the implementation, but spec and README/runbook are stale: acce |
| K07-performance | kimi | 0.95 | PASS | Commit modifies only CLI command visibility flags and an offline mutation-canary |
| K08-dependencies | kimi | 0.95 | PASS | No new pip packages introduced; the diff touches only application code and tests |
| K09-security | kimi | 0.95 | PASS | Diff introduces no credential handling, no env-var emission, no redaction bypass |
| K10-scope-creep | kimi | 0.30 | STOP | The commit bundles unrelated W11-MUTATION-PATTERN-EXPANSION changes and unused S |
| M01-architecture | mimo | 0.95 | PASS | The commit cleanly extends existing CLI (Click group pattern), mutation testing  |
| M02-safety | mimo | 0.95 | PASS | Commit adds only declarative click hidden=True flags, a pure-function pattern pi |
| M03-operator-ux (FAIL) | mimo | — | ? | engine returned empty/error: None |
| M04-cross-platform | mimo | 0.95 | PASS | No Windows-specific assumptions found; pure Python changes to CLI visibility and |
| M05-agent-ux (FAIL) | mimo | — | ? | engine returned empty/error: None |
| M06-audit-criteria | mimo | 0.78 | PASS | The spec's acceptance criteria are mostly testable but have two concrete gaps: ( |
| M07-spec-drift | mimo | 0.55 | PASS | Spec requires ≤10 daily-use verbs in default --help and 'hosting' verbs under th |
| M08-forward-compat | mimo | 0.00 | ? |  |
| M09-code-review | mimo | 0.00 | ? |  |
| M10-regression-risk | mimo | 0.85 | PASS | The hidden=True + backward-callability contract is well-guarded by parametrized  |

## Blocking concerns (personas with conf < 0.7)

- **K02-test-quality** (0.55): Rubber-stamp assertion `found >= 5` in test_advanced_list_subcommand_works would pass if the list omitted most hidden verbs, and the complete absence of alias or real-invocation coverage means the suite stays green even if the backwards-compat wiring is hollow.
- **K10-scope-creep** (0.30): The `advanced` group docstring advertises invocation of engineering-tier verbs yet provides no subcommands for them, creating a misleading maintenance surface that does not satisfy the namespace requirement and will require a breaking refactor to actually host the verbs.
- **K03-api-surface** (0.30): Agent calling `harness advanced <verb>` will receive 'No such command' because the group does not host the verbs, a direct API-surface footgun.
- **M07-spec-drift** (0.55): none — the ≤10 gap is a concrete spec violation but the hidden-verbs-still-callable contract is met and the STATUS.csv was updated; this is drift worth logging, not a shipping blocker
- **M08-forward-compat** (0.00): (no concern text)
- **M09-code-review** (0.00): (no concern text)
- **K04-error-handling** (0.30): Unaudited silent-except in load-bearing canary script plus unhandled file-read crash yielding stack trace to operator.
- **K06-documentation** (0.40): Agent reading the spec would expect `harness advanced <verb>` namespaces and deprecation aliases; the undocu​mented spec-code mismatch violates the documentation self-sufficiency contract.
- **K01-correctness** (0.20): The specified namespace reorganization is absent: engineering verbs are not subcommands of `harness advanced`, remaining top-level hidden commands instead, which breaks the required CLI contract.
