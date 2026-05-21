# Proxy key disable states — recovery map (2026-05-21)

The 4-key proxy can disable an API key in 4 ways.  Each has its own
reset path.

| State | Trigger | Reset verb | Notes |
|---|---|---|---|
| circuit_state OPEN | 3 consecutive failures | `harness proxy reset-circuit <alias>` OR wait for cooldown_until | Auto-recovers when cooldown elapses |
| permanent + auto_quarantined_at | 3 flaps in 60min (AUTO-QUARANTINE-KEY) | `harness proxy unquarantine <alias>` | L4 escalation file at coord/observer/escalations/flap_*.json |
| permanent + (no auto_quarantined_at) | Operator ran `harness proxy quarantine <alias>` | `harness proxy unquarantine <alias>` | Manual reset only — no automatic recovery |
| loop_status="stopped" | kill_conditions L4 fired | `harness loop start` re-arms; check coord/dev_loop/escalations[] | Not key-specific; the whole loop halts |

For a single-shot "clear everything" recovery:

```
harness proxy unquarantine --all
harness proxy reset-circuit --key-id ALL   # if separate
harness loop start --cadence-minutes 30
```
