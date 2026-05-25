Given the constraints (1–3 hours, 24h test running, $4.80 budget, operator non-technical), here’s the brutally honest ROI ranking. **Busy-work**: `W12-MYPY-STRICT-GATE-CI` (no operator value), `W12-MORNING-EMAIL-BRIEF` (SMTP complexity + 4h block = out of time tonight). **High-ROI**: dashboard widgets → live engine smoke test → email brief (if hours expand).

---

## Ranked Moves

### 1. DASHBOARD-COST-WIDGET-HTML
**Pitch** – The operator can’t see cost; render `/api/cost` on the dashboard so they know budget used at a glance without reading raw JSON.

**Concrete changes**
- `src/harness/dashboard/src/App.tsx` – add a `<CostWidget>` component
- `src/harness/dashboard/src/components/CostWidget.tsx` – new file: fetches `/api/cost`, shows `$XX.XX / $5.00` bar
- `src/harness/dashboard/templates/index.html` – no change (React SPA)
- **No backend changes** – `/api/cost` already exists (from W12-A)

**Time estimate** – 1.5–2 hours (React component + tests + Dashboard snapshot update)

**Why ROI beats alternatives** – Highest operator UX impact per hour: solves the #1 visibility gap. Zero backend risk, zero engine cost, no CI flake. Burdens the backlog by one row (this is explicitly W12-B). Audit trail benefit: cost visible in dashboard screenshots.

**One risk** – The dashboard is currently a static HTML/JS bundle; if not using React, the implementation might be raw. Need to confirm dev server + build pipeline works without blocking the 24h test. Risk low (5%).

---

### 2. DASHBOARD-L5-BANNER-HTML
**Pitch** – Mirror of cost widget but for `/api/l5-events`; show latest L5 audit trail directly on the home page.

**Concrete changes**
- `src/harness/dashboard/src/components/L5Banner.tsx` – new file: fetches `/api/l5-events`, renders last 3 events with timestamps
- `src/harness/dashboard/src/App.tsx` – add `<L5Banner>` below cost widget

**Time estimate** – 1–1.5 hours (even simpler than cost widget because it’s just a list)

**Why ROI beats alternatives** – Builds on #1, uses same backend. Completes two backlog rows in <3 hours. Directly improves debuggability (operator sees L5 events without SSH). High burndown momentum.

**One risk** – If `/api/l5-events` is slow (aggregates across sessions), it could annoy operator. Add a 5-second fetch timeout and graceful empty state. Risk low (5%).

---

### 3. LIVE-ENGINE-SMOKE-HARNESS (weekly CI)
**Pitch** – Replace mock-only engine tests with a real Kimi/DeepSeek/MiMo smoke test to prevent silent API drift – critical for any agent that uses `harness.dispatch` after a fresh clone.

**Concrete changes**
- `.github/workflows/engine-smoke.yml` – new file: weekly cron (e.g., Saturday 06:00 UTC), matrix on `ENGINE=openrouter/{kimi,deepseek,mimo}`, calls `pytest tests/test_engine_smoke.py -x`
- `tests/test_engine_smoke.py` – new file: simple `harness.dispatch("Hello")` assertion for each engine, configured via env vars (API keys from GitHub secrets)
- `src/harness/_config.py` – minor tweak to allow CI to set `HARNESS_BUDGET=0.02` (cost per test ~$0.01)

**Time estimate** – 2.5–3 hours (CI YAML, test file, secrets docs, dry-run)

**Why ROI beats alternatives** – Highest **agent-facing** value: without this, a new operator clone gets zero real-engine validation. It directly prevents the `fresh-clone -> dispatch fails -> wasted debugging` scenario. Burdens backlog (one row). Low operator UX gain but essential for engineering integrity.

**One risk** – Flaky API responses could turn the weekly run into a noise generator. Mitigate by requiring 2/3 engines to pass, and skip failures on 429/503. Also cost: ~$0.04/week = negligible. Risk medium (15%) – but acceptable for 3 hours.

---

### 4. MORNING-EMAIL-BRIEF (only if 3+ hours remain after widgets)
**Pitch** – Automate a daily email summary of harness health so the operator doesn’t need to open a browser – but this is a **lower priority** tonight because the dashboard already solves real-time visibility.

**Concrete changes**
- `src/harness/emails/brief.py` – new module: fetches `/api/health`, `/api/cost`, `/api/l5-events`, composes HTML email
- `src/harness/cli.py` – add `--dispatch-email` flag to send via SMTP (uses environment variables for credentials)
- `Cargo.toml` (if Rust backend) or `requirements.txt` – add `smtplib` (Python stdlib) or `lettre` (Rust). Actually harness is Python; `smtplib` is built-in.

**Time estimate** – 3.5–4 hours (design, implementation, test with a real SMTP relay, handling errors). **Exceeds the window** unless combined with widget work. ROI for operator is moderate – they already have dashboard and observer cron.

**Why ROI beats alternatives** – Only if 24h test reveals connectivity issues; otherwise busy-work. Email is fragile (firewalls, spam filters). Not recommended tonight.

**One risk** – SMTP credentials leak if not stored in secrets. Risk of email deliverability issues creates false alarms. Risk medium-high (50%).

---

### 5. MYPY-STRICT-GATE-CI (busy-work)
**Pitch** – Add `mypy --strict` to CI to enforce type hygiene.

**Concrete changes**
- `.github/workflows/ci.yml` – add step `mypy --strict src/harness/_sdk.py` after tests

**Time estimate** – 1 hour (but likely minutes)

**Why it’s busy-work** – Zero operator UX impact. Zero agent value. Will not uncover bugs in the SDK (already 2165 tests). Only helps if someone introduces type issues later. **Lowest ROI tonight** – do not touch.

---

## Single Top Recommendation

**Implement DASHBOARD-COST-WIDGET-HTML** – highest operator UX gain per hour, zero risk, directly burns down a backlog row, and sets up the operator to see cost without asking.

**First command to execute**:

```bash
cd src/harness/dashboard && touch src/components/CostWidget.tsx && echo "Added stub; now implement fetch /api/cost and render gauge"
```

Then:  
- Open `src/components/CostWidget.tsx` in editor  
- Write a React component (or vanilla JS if not using React) that calls `fetch('/api/cost')` once on mount, displays `$XX.XX / $5.00` with a progress bar  
- Insert `<CostWidget />` into `App.tsx`  
- Run `npm run build` (or equivalent), then reload `http://localhost:8765` to verify  
- Update `STATUS.csv` to mark `W12-DASHBOARD-COST-WIDGET-HTML` as SHIPPED  

Total time: ~1.5h. If done before 23:00 UTC, it may make the daily retro.