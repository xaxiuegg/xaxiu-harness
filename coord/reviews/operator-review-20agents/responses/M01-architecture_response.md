### Verdict

`NEEDS-WORK`

### Confidence

0.82

### Analysis

The SDK core (`dispatch`, `retrieve`, `budget_status`) composes cleanly — the E2E proof at evidence 18 validates real round-trips against three engines with ~30× context-cost reduction. The inter-module seams inside `harness/` are architecturally sound: `_sdk.py` → `dispatcher.dispatch_packet` → `engines/concrete.py` → `dispatch_cache` → `retrieve`, with the `_ensure_default_adapter` bootstrap closing the only real field-test gap. The agent quickstart (evidence 17) documents a coherent 5-command onboarding flow.

**The friction is in the surfaces, not the core.**

Three concrete composition failures an agent or operator hits:

1. **CLI crashes on the dominant platform.** Three independent paths (`preflight`, `--help`, `agent init`) throw `UnicodeEncodeError` against Windows cp1252 (evidence 04 line 56–63, evidence 06 line 56–63, evidence 15 line 56–63). These aren't edge cases — `preflight` is the autonomous-mode gate, `--help` is the first-touch surface, and `agent init` is the entry verb. The quickstart itself acknowledges this (evidence 17 §3: "crashes Windows console") but shipped anyway. A non-ASCII arrow (`→`), alpha (`α`), and checkmark (`✓`) defeat every one. This is a systemic `click.echo()` call-site problem, not three independent bugs — the fix is `click.echo(text, err=False, color=False)` with `encoding='utf-8'` or a one-line `sys.stdout.reconfigure(encoding='utf-8')` at the CLI entrypoint.

2. **Dashboard API surface is a ghost ship.** Four of four queried dashboard API endpoints return `{"detail":"Not Found"}` (evidence 09, 12, 13, 14). The STATUS tracker claims `W3` (dashboard backend) shipped and `DASHBOARD-V2-ROUTES` landed, but the live server at `:8765` doesn't serve `/api/loop`, `/api/cost`, `/api/preflight-latency`, or `/api/l5-events`. The frontend dashboard screenshot (evidence 00) shows the same stale loop (tick=11, last-tick `2026-05-21` — **three days old**) with zero Wave 11 surfaces (