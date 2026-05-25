**Sunday evening move: extend the dashboard so the 24h test feels alive.**

Here are four ranked moves that ride the rc.1 momentum without touching the running harness process.

---

### 1. L5 Live Banner Sprint
- **Pitch:** Surface the 24h autonomous heartbeat as a color-coded dashboard banner so the system feels like it’s speaking to you in real time.
- **Concrete deliverable:** `localhost:8765` renders a dismissible top banner polling `/api/l5-events` every 30 s, showing latest cycle time and an OK/WARNING/ERROR badge.
- **Time estimate:** 2h
- **Why this beats sitting idle:** It turns the invisible background test into a visible, living thing. Builds directly on the W12-A dashboard fixes you just shipped.

### 2. Mypy Strict Gate — CI in One Shot
- **Pitch:** Let the harness audit its own SDK types, then lock the standard into GitHub Actions so rc.2 is automatically guarded.
- **Concrete deliverable:** `.github/workflows/mypy-strict.yml` passing on `src/harness/_sdk.py` with a green checkmark on the next push.
- **Time estimate:** 1h
- **Why this beats sitting idle:** Zero runtime risk, pure quality closure. Satisfying “green check” dopamine hit that hardens the release without disturbing the 24h run.

### 3. Max-Token Power-Up
- **Pitch:** Implement the defaults bump you just approved—raise to 8000, normalize param names across Kimi/DeepSeek/MiMo, and add a `--quick` flag so deep reviews become default.
- **Concrete deliverable:** A single commit where `harness dispatch` defaults to 8k tokens and `harness dispatch --quick` drops to the old fast default.
- **Time estimate:** 2h
- **Why this beats sitting idle:** Directly capitalizes on the Aquinas demo. Makes the harness feel materially more capable for the next real review you run.

### 4. Cost Widget on the Glass
- **Pitch:** Turn the live `/api/cost` endpoint into a real-time budget gauge so your remaining $4.80 headroom is visible as a progress bar.
- **Concrete deliverable:** A cost card on `localhost:8765` showing `$0.20 / $5.00`, percent-used, and a “safe to spend” indicator.
- **Time estimate:** 3h
- **Why this beats sitting idle:** Money is visceral. Watching the widget creep during the 24h test is hypnotic and proves the API-to-UI pipeline end-to-end.

---

## Top recommendation
**Go with Move 1 (L5 Live Banner Sprint).**  
It is the optimal fun/momentum trade: 2 hours, purely additive, no scope debate, and it makes the dashboard *feel* like a mission-control screen for the test that is literally running right now. You get to watch something you built glow green before you sleep.

### First concrete command to execute
```bash
harness dispatch \
  --engines Kimi,DeepSeek,MiMo \
  --file src/harness/dashboard/static/index.html \
  --prompt "Add a live L5 status banner at the very top of this dashboard HTML. It should poll /api/l5-events every 30 seconds and display the latest event: a green badge for OK, yellow for WARN, red for ERROR, plus the event timestamp and a dismiss button. Return only the complete modified HTML file." \
  --out ./W12-L5-banner-draft.html
```
*(After the engines return, paste the best draft into the dashboard static file, hit refresh on `localhost:8765`, and watch the banner pick up your running test.)*