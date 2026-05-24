### Verdict

`NEEDS-WORK`

Wave 11's CLI spine and SDK contract are solid, but **three spec promises are marked shipped while the live harness demonstrably fails to deliver them**: the dashboard cost widget (API 404), `mypy --strict` (not in CI), and the morning email brief (deferred but listed in the closeout as "shipped" context). Additionally, a pervasive Windows Unicode encoding bug crashes at least 3 CLI verbs on the operator's actual machine. These are fixable in <1 day.

---

### Confidence

**0.78**

High confidence on the gap analysis — the evidence is direct (404s, Unicode tracebacks, three-day-stale dashboard). Moderate uncertainty because I cannot verify the `wave-11-plan.md` acceptance criteria file itself (it's referenced but not among the 20 evidence files, so I'm inferring from STATUS.csv notes and the closeout narrative).

---

### Top-3 concrete recommendations

**1. Fix the Windows cp1252 Unicode crash — it blocks the very CLI verbs Wave 11 shipped.**
Three different commands (`preflight`, `harness --help`, `agent init`) crash identically with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` / `'\u03b1'` / `'\u2713'`. The operator's Windows console defaults to cp1252, and every rich output (arrow `→`, checkmark `✓`, Greek `α`) blows up *after* the work completes, so data is written but the operator sees a traceback instead of the confirmation. Fix: wrap `click.echo()` in a UTF-8 `StreamWriter` fallback, or strip non-ASCII from Windows console output paths.
- **Evidence**: `04_preflight.txt` line 32–41, `06_harness_help.txt` line 1–20, `15_agent_init_dry.txt` line 1–14
- **Effort**: **S** (~1 hour; a single utility function `safe_echo(text)` with `errors='replace'` guard)

**2. Wire the dashboard to the APIs that already exist in the backend — the dashboard is a dead screen right now.**
The dashboard screenshot shows 0 cost widget, 0 L5 banner, 0 latency surface, 0 queue visibility. The backend code ships all four (`/v2/cost-panel`, `/api/queue`, `snapshot.v2`, `snapshot.queue`) but the HTML frontend never received the Wave 11 work. STATUS rows W11-COST-VISIBILITY-WIDGET and W11-L5-OUTPUT-CONTRACT are marked shipped, yet the dashboard — the one place a non-technical operator would look — renders none of it. `/api/loop` and `/api/cost` both return `{"detail":"Not Found"}`.
- **Evidence**: `00_dashboard_screenshot.png` (description), `09_dashboard_api_loop.json`, `12_dashboard_api_cost.json`, `14_dashboard_api_l5_events.json`
- **Effort**: **M** (~3–4 hours; frontend HTML/JS for the 4 widget panels + verify API routes mount correctly)

**3. Run `mypy --strict src/harness/_sdk.py` and gate it in CI — the spec explicitly named this as acceptance criteria.**
W11-PYTHON-SDK-API-IMPL notes say "mypy --strict; final release gate." The closeout narrative lists it as open gap #4. The SDK is the agent-facing contract; a type error there is a silent breakage for every downstream agent. Adding a CI step is a one-liner in `.github/workflows/test.yml`.
- **Evidence**: `16_wave_11_closeout.md` section "Recommended next-wave directions" item 4
- **Effort**: **S** (~1–2 hours; fix whatever `--strict` surfaces on `_sdk.py` + add CI step)

---

### Operator vote

`WAIT-FOR-WAVE-12`

The Unicode crash alone means the operator cannot use `harness preflight`,