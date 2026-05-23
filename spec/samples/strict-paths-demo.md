# SPEC-ID: strict-paths-demo — W5-BB strict-path feature demonstration

## Goal

Create a small "engine reliability cheat sheet" markdown file documenting
the three engines (Kimi K2.6, MiMo Pro v2.5, DeepSeek v4-flash), their
recommended use cases, and known failure modes.  The file MUST be at the
exact path declared under Strict Paths so the operator can reliably bind
this deliverable into release notes or onboarding flows.

## Strict Paths

- coord/operator/engine-cheatsheet.md

## Acceptance

1. The file at `coord/operator/engine-cheatsheet.md` exists in the
   worktree post-dispatch.
2. The file mentions all three engines by name: Kimi, MiMo, DeepSeek.
3. The file has at least one bulleted list (engines + use cases).
4. No tests required — this is a documentation deliverable.

## Why this spec exists

W5-BB landed worker strict-path mode but had no operator-facing sample
exercising the syntax.  This spec serves as both:

- A canonical example of the `## Strict Paths` section format.
- A regression check — if a future change breaks strict-path
  enforcement, running this spec via `harness queue execute` will
  surface the regression because the worker will create a file at the
  wrong path and the harness will mark `tests_passed=False` with
  `error_tag=L3.worker.E_STRICT_PATH_MISSING`.
