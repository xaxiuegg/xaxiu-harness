### 1. Lens-specific findings

**Finding 1 — The SDK is missing the tool’s highest-value operation.**  
The SDK exports only “3 public functions (`dispatch`, `retrieve`, `budget_status`) plus `DispatchResult`”, yet the master audit identifies `harness review` as “the most concrete value-prop we have.” Keeping `review` trapped in `src/harness/cli.py` forces agents to shell out, burning the exact context window the harness was built to preserve.

**Finding 2 — The operator already treats the SDK as the real interface.**  
The runbook’s own daily-use examples show the operator bypassing the CLI:  
> “`PYTHONPATH=src python -c "import harness; r = harness.dispatch('Your prompt here', engine='kimi')"`”  
This proves the CLI is too coarse for programmatic use and the SDK is where the real surface lives.

**Finding 3 — The CLI has become a monolith serving two masters.**  
> “Audience B: operator / dev-Claude doing operations… 30+ CLI verbs + their flags… Bloat risk: MEDIUM and growing.”  
Every new verb is cognitive debt. The CLI is trying to be both a human TUI and an automation API; it should be neither. It should be a thin wrapper.

**Finding 4 — Backup encryption is architectural theater.**  
The bloat audit already asked the right question:  
> “Backup encryption (W13-BACKUP-ENCRYPTION row): genuine security need or paranoia for an internal tool where .env is already on disk in cleartext?”  
Encrypting backups while live secrets sit in plaintext `.env` is false security; it adds code, key-management, and recovery complexity for no real threat-model benefit.

**Finding 5 — The three layers are already informally present but not enforced.**  
> “`harness advanced list` hides 13 engineering verbs from `--help`”  
and  
> “Operator's job should be policy ('how much to spend per session'), not procedure ('did I rotate the cache today').”  
We should formalize the split: **SDK** (agents + operator scripts), **Operator-CLI** (daily human verbs only), **Maintainer-internals** (hidden advanced verbs). Right now the boundary is accidental.

**Finding 6 — Plugin sandboxing is over-engineering for an internal tool.**  
The Horizon C plan explicitly states the correct posture:  
> “accept the risk and document it (since internal-tool = trusted authors).”  
Building a sandbox or signature pipeline for `plugins/lenses/` adds ABI complexity that benefits no one in a single-operator, trusted-author context.

**Finding 7 — Multi-user architecture should not inflate the SDK until there is a team.**  
> “Skip this wave entirely if the operator works solo.”  
Carrying