# Audit engine choice — W10-MIMO-FILTER-INVESTIGATION

**Authored**: 2026-05-25 per W10-MIMO-FILTER-INVESTIGATION (queued
from W9 closeout when every W9 audit hit MiMo's content filter).

## Problem

Every W9 audit ran via `scripts/audit_task_with_mimo.py` blocked
in the MiMo primary path for ~60s (MiMo returned an "internal"
error consistent with a content-filter hit) before falling back to
DeepSeek.  DeepSeek then served the audit cleanly in ~30s.

Per `coord/reviews/wave-9-closeout.md` audit roll-up: 5 out of 5
W9 avg-of-3 audits hit this same pattern.  Each avg-of-3 spent
60s × 3 = 180s waiting for MiMo before DeepSeek-fallback.  Across
the 5 audits that's 15 minutes of wasted wall-clock per wave purely
on the wrong-engine-first.

## Root cause

MiMo's content filter rejects prompts containing certain combinations
that the harness audit prompt happens to trip:

- The prompt names live API keys verbatim (`KIMI_API_KEY`,
  `DEEPSEEK_API_KEY`) when describing failure modes.
- The diff excerpts include real-world commit content from the
  harness, which often mentions security topics (DPAPI, secret
  redaction, prompt injection) — all topics that trip MiMo's
  content filter.

The filter trips during the *audit prompt itself*, not during the
generated response.  No amount of prompt restructuring will reliably
avoid it as long as the harness ships features about secret
handling, prompt injection guards, and credential management.

## Decision

**Demote MiMo to fallback; promote DeepSeek-v4-flash to primary.**

Rationale:

- DeepSeek-v4-flash has a 1M-token context window vs MiMo's 131k —
  the larger window matters as the harness grows.
- DeepSeek doesn't have MiMo's content filter; the audit prompts
  about security/secrets/redaction won't trip it.
- DeepSeek-v4-flash is per-token but cheap (~$0.1/M tokens input);
  W9 saw ~5 audits × ~60k tokens each = 300k tokens ≈ $0.03/wave.
  Vs MiMo subscription which is sunk cost but currently providing
  zero W9 audit value.
- MiMo stays as fallback for when DeepSeek is unreachable (network
  outage, rate-limit) so the audit pipeline still has redundancy.

## Implementation

`scripts/audit_task_with_mimo.py` `_dispatch_with_fallback`
already implements a fallback chain.  Change:

  Before:  primary=MiMo  ->  fallback=DeepSeek
  After:   primary=DeepSeek  ->  fallback=MiMo

Comment in the script preserves the W6-A2 audit-script-hardening
rationale (MiMo content filter detection) for future readers.

The script's name (`audit_task_with_mimo.py`) stays as a deprecated-
but-stable filename to preserve git history + every existing
audit_wave*_all.py driver's references.  Aliasing or renaming is
W11 work if it ever surfaces as an operator pain point.

## Acceptance

- Audit prompt unchanged.
- Engine selection swapped: DeepSeek primary, MiMo fallback.
- Latency per W10 audit should drop from ~180s (avg-of-3 with MiMo
  failures) to ~30-90s (DeepSeek direct, no failover).
- Tests verify the new primary is used + fallback still works.

## Re-evaluation trigger

If MiMo content filter ever changes (Moonshot tunes it down) or
DeepSeek becomes unreliable, revisit the primary choice.  Track
in `coord/engine_performance_log.md` per
[[feedback_cross_engine_fallback]] memory.

— End decision doc —
