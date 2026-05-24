<!-- name=M2-process latency_ms=29482 error='' -->

## 1. Next-Best Move

**W8-STOP-HOOK-DEBOUNCE** — rewrite the stop-hook's dirty-file check to exempt mutation-sweep artifacts (or debounce by comparing STATUS.csv content-hash instead of mtime). Six hook fires across W7 each burned a turn just to `touch STATUS.csv`. That's 6 lost turns of autonomous execution on the cleanest wave yet. The hook is meant to catch real drift; right now it's a false-positive machine. Fix it and W8+ waves ship faster with less operator babysitting.

## 2. Working / Not Working

**Working — preserve:**
- **"Proceed per rec" delegation.** Operator trusts panel synthesis → Claude executes linearly without second-guessing. W7 proved this: 8/8, 0 STOPs. The operator's role is *choose the composite move*, Claude's role is *ship it*. That contract is clean.
- **Honest closeout reporting.** W6 documented both STOPs without spec-shaping to override the gate. That builds trust and gives the panel real signal to work with.

**Not working — replace:**
- **Stop-hook as status oracle.** It fires on mtime churn, not semantic drift. Every fire costs a turn + operator attention. Replace with content-hash or a debounce window.
- **Escalation threshold is too coarse (L5 only).** W6-B1 shipped as "partial" without escalation. A transport module going unmerged is arguably L4, but Claude had no mechanism to flag it — it just shipped partial. There needs to be a mid-tier signal: "not blocking, but operator should know."
- **Latent config bugs surface by accident.** Kimi's max_tokens=4000 eating the reasoning budget was found only because the operator eyeballed empty panel returns. There's no automated "did this call return empty content?" guard. That's a process gap, not a one-off.

## 3. Next 2–3 Waves — Theme

**"Tighten the detection layer."** The *execution* layer is now strong (worker pipeline, transport ABC, mutation infrastructure). What's weak is *automated feedback*: the stop-hook is noisy, audit gates required 3 retries to articulate what they actually wanted (behavioral integration vs. unit sentinel), and there's no guard against silent empty returns from any engine. The next waves should make the harness *self-noticing* — debounced hooks, response-non-empty guards, audit criteria that get written down before the sweep runs, not retrofitted after the third STOP. The goal: the operator shouldn't need to eyeball anything to keep the wave clean.
