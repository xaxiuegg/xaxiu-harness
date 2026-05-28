# Key rotation playbook — xaxiu-harness

**Audience**: the operator (you). When an API key needs to be rotated — whether for hygiene, after a leak, after a provider terminates the account, or as part of a periodic rotation — this is the procedure.

**Verb**: `harness env-rotate <engine>` (W14-KEY-ROTATION-PLAYBOOK, shipped 2026-05-28).

---

## When to rotate

| Scenario | Severity | Action |
|---|---|---|
| **Suspected leak** (key appeared in a log, screenshot, chat, public commit, support ticket) | HIGH | Rotate IMMEDIATELY with `--no-keep-previous` so the old key is destroyed. Notify the provider — most have a key-rotation endpoint that revokes the old key server-side. |
| **Provider terminated the account** (Kimi-style 2026-05-22 termination) | HIGH | Acquire a new account/key. Rotate the local secret. Update any policy decisions (e.g., 2026-05-25 plan switched the $50 slot from Kimi → Qwen 3.6 Plus). |
| **Periodic rotation** (quarterly hygiene) | LOW | Rotate with `--keep-previous` (default) so 24h rollback is available. Smoke-test before deleting the backup. |
| **Post-incident** (suspected compromise discovered after the fact) | HIGH | Rotate ALL engines, not just the suspected one. Audit `~/.harness/audit.jsonl` for the incident window. Verify chain integrity with `harness audit verify`. |

If you're unsure of severity, default to the higher one. A rotation is always cheaper than a re-incident.

---

## The verb

```bash
# Interactive (recommended for manual rotation):
harness env-rotate deepseek
# → prompts for the new key (hidden input)
# → preserves old key as DEEPSEEK_API_KEY_PREVIOUS_<timestamp>
# → emits a key_rotation event into the chained audit ledger

# Scripted (for automation):
echo "$NEW_KEY" | harness env-rotate deepseek --from-stdin

# Hostile compromise (destroy old key immediately):
harness env-rotate deepseek --no-keep-previous

# Preview without touching DPAPI:
harness env-rotate deepseek --dry-run
```

Supported engines (short names): `deepseek`, `kimi`, `mimo`, `anthropic`, `gemini`, `qwen`.

The verb maps the short name to its canonical env-var name (e.g., `qwen → DASHSCOPE_API_KEY`) and rotates the DPAPI secret of that name.

### What it does, step by step

1. **Maps engine → env var** via the canonical lookup. Unknown engines → exit 1 with the supported list.
2. **Reads the new key** (hidden prompt OR stdin).
3. **Validates** non-empty. Empty → exit 2 with "rotation cancelled."
4. **Atomically rotates** via `harness.secrets.dpapi.rotate_secret`:
   - Reads the current value (if any).
   - Writes the backup `<NAME>_PREVIOUS_<UTC-timestamp>` FIRST (two-phase, so a crash mid-rotation leaves a recoverable state).
   - Writes the new value (overwrites the live key).
5. **Emits an audit event** into `~/.harness/audit.jsonl`:
   ```json
   {"ts": "...", "event": "key_rotation", "provider": "deepseek",
    "previous_kept_as": "DEEPSEEK_API_KEY_PREVIOUS_20260528154500",
    "had_previous_value": true,
    "prev_hash": "...", "hmac": "..."}
   ```
   This participates in the W14-AUDIT-CHAIN-HMAC chain — rotations are tamper-evident.
6. **Prints the next-step recipe** (smoke test + backup deletion).

The verb NEVER logs the key value, NEVER includes it in exception messages, NEVER stores it in plaintext anywhere.

---

## After rotation — smoke test

The rotation succeeded ≠ the key works. Before deleting the backup, confirm the live key actually dispatches:

```bash
harness ask --engines deepseek "Reply with: OK"
```

A successful answer means the key works. If you get an auth error, see "Rollback" below.

For Qwen specifically (which gates on `DASHSCOPE_API_KEY`):

```bash
harness ask --engines qwen "Reply OK."
```

If you have the W14-KIMI-REPLACEMENT-WITH-QWEN scaffold (commit `522df36`) but no live key yet, the smoke test surfaces the auth error cleanly.

---

## Rollback (within 24h)

If the new key fails the smoke test and `--keep-previous` was on (the default), restore the old key:

```bash
# Find the backup name from the rotation output, e.g.:
#   previous kept as: DEEPSEEK_API_KEY_PREVIOUS_20260528154500
python -c "
from harness.secrets.dpapi import decrypt_secret, encrypt_secret
old = decrypt_secret('DEEPSEEK_API_KEY_PREVIOUS_20260528154500')
encrypt_secret('DEEPSEEK_API_KEY', old)
print('rollback complete')
"
```

After rollback, investigate why the new key failed before retrying. Common causes:
- Pasted with leading/trailing whitespace (the verb strips outer whitespace but not embedded ones)
- Wrong provider (e.g., DashScope key pasted into DeepSeek slot)
- Key not yet activated (some providers require a few minutes to propagate)

If you missed the 24h backup window (or used `--no-keep-previous`), you must re-acquire the key from the provider's dashboard.

---

## Cleanup — after the smoke test passes

The backup secret lingers in DPAPI taking up space and slightly widening the attack surface. Delete it once you've confirmed the new key works:

```bash
python -c "
from harness.secrets.dpapi import delete_secret
delete_secret('DEEPSEEK_API_KEY_PREVIOUS_20260528154500')
print('backup deleted')
"
```

For batch cleanup of stale backups (>7 days old), list with:

```bash
python -c "
from harness.secrets.dpapi import list_secrets
for name in list_secrets():
    if '_PREVIOUS_' in name:
        print(name)
"
```

---

## Cross-platform note

The DPAPI store is Windows-only. On Linux/macOS:

- The verb exits with code 3 and prints: `On Linux/macOS, set the env var directly: export DEEPSEEK_API_KEY=<new-value>`.
- The chained audit ledger still records the rotation IF you set `HARNESS_AUDIT_HMAC_KEY` (env var) — see [coord/CURRENT_PLAN.md](../coord/CURRENT_PLAN.md) "2026-05-28 PM — audit chain HMAC shipped" for the chain mechanism.

A future row could add cross-platform keyring support (per `python -c "import keyring; keyring.set_password(...)"`); not in scope for this playbook.

---

## Verification — the rotation event in the audit ledger

After rotating, the audit ledger should have a new `key_rotation` event:

```bash
# Find recent rotations:
harness audit show --since-hours 24 --format json | python -c "
import sys, json
events = json.load(sys.stdin)
for ev in events:
    if ev.get('event') == 'key_rotation':
        print(f\"{ev['ts']}  {ev['provider']}  prev={ev.get('previous_kept_as') or 'discarded'}\")
"

# Verify the chain still passes:
harness audit verify
```

A rotation event with `prev_hash` + `hmac` indicates the chain was active at rotation time. If verification fails AFTER a rotation, investigate immediately — either the chain key changed (re-rotation of the chain secret itself) or genuine tampering occurred during the window.

---

## Provider-specific cheat sheet

| Engine | Env var | Provider dashboard | Notes |
|---|---|---|---|
| **deepseek** | `DEEPSEEK_API_KEY` | https://platform.deepseek.com | PAYG; `$0.21/M` blended at v4-flash tier |
| **mimo** | `MIMO_API_KEY` | https://mimo.com (Token Plan UI) | Standard tier `$14.08/mo`; `sk-` or `tp-` prefix possible |
| **qwen** | `DASHSCOPE_API_KEY` | https://dashscope.aliyun.com | PAYG only — NOT the Alibaba Coding Plan subscription |
| **anthropic** | `ANTHROPIC_API_KEY` | https://console.anthropic.com | Optional — operator uses Claude Code direct |
| **gemini** | `GEMINI_API_KEY` | https://aistudio.google.com | Optional secondary engine |
| **kimi** | `KIMI_API_KEY` | (provider terminated 2026-05-22) | Adapter retained for any operator who later acquires a Moonshot-approved client license; otherwise replaced by Qwen 3.6 Plus per strategic plan |

---

## Operator memory & links

- [feedback_xaxiu_harness_full_dev_authority] — full dev authority on this project; rotation is in-scope and doesn't need per-action approval, but credentials remain the operator's to acquire.
- [feedback_no_env_value_leak_in_shell_checks] — when verifying key presence in shells, use `[ -n "$VAR" ] && echo SET`. Never `${VAR:+SET}${VAR:-MISSING}` (leaks the value when set).
- The W14-AUDIT-CHAIN-HMAC chain extends to rotation events — every rotation is tamper-evident.

If this playbook is wrong, edit it. The doc is meant to be the operator's first stop, not a museum piece.
