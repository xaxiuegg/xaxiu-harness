### Stance summary (3-5 sentences)

xaxiu-harness just lived through its first real security incident: Kimi silently terminated our account, and we only noticed mid‑panel because the previous engine‑health probe called any HTTP response “up.” That’s a blast‑radius failure. The new `W13-ENGINE-FAILURE-VISIBILITY` layer now correctly categorizes `terminated`, but we still lack three things v1.0.0 should have had: **backup secret redaction** (a backup tar of `~/.harness` contains the now‑dead Kimi key), **integrity chaining on the audit log** (anyone with write access to the file can silently delete rows), and a **key‑rotation procedure** that doesn’t force the operator to reverse‑engineer env‑var + backup cleanup manually. The most important property to strengthen is **detectability + recoverability of secret compromise** — not just for the dispatch path (already good), but for every persistent state file and every backup.

### Top 3 rows to ship next (ranked)

---

#### 1. W15-AUDIT-LOG-CHAIN-OF-INTEGRITY
- **Title**: HMAC‑chain every audit.jsonl row so tampering is detectable
- **Estimated effort**: **M** (3–4h)
- **Why this row, by YOUR lens**: Today `audit.jsonl` is an append‑only blob. An attacker (or a stray `sed` in a session) can delete, reorder, or truncate rows with zero forensic evidence. HMAC‑chaining (each row includes an HMAC over the previous row’s HMAC + payload, keyed by a derived key from a file‑local secret + a passphrase stored somewhere safe) makes post‑hoc integrity verification possible — and necessary for any audit subpoena or incident post‑mortem. This is the single biggest audit‑trail weakness.
- **Acceptance criteria**:
  - `AuditLedger.append_row()` writes `{..., "hmac": "<hex>"}`; HMAC covers `prev_hmac` + `timestamp` + `event` + `redacted_payload`.
  - New CLI verb `harness audit verify` reads the chain, recomputes HMACs, and reports first‑broken index + row.
  - `W13-AUDIT-JSONL` existing rows are backfilled with `prev_hmac=None` for the first row; the first row uses a static seed HMAC.
  - Key material is derived from `~/.harness/audit_key` (created automatically on first write, 32‑byte random, **never** logged or backed up unless explicitly requested).
  - Test: corruption of any row (remove, reorder, change a character) causes `verify` to fail with exact location.

---

#### 2. W14-BACKUP-SECRETS-REDACT (already in CURRENT_PLAN.md, but expand scope)
- **Title**: Full redaction sweep on backup contents + hash‑verify during restore
- **Estimated effort**: **M** (3–4h)
- **Why this row, by YOUR lens**: The DeepSeek panel found that `~/.harness/backup/` tarballs may contain API keys — exactly the kind of thing we just saw with the terminated Kimi key. If that backup is restored onto a new machine, the old dead key sits there. Worse, an attacker who gets a backup gets a bunch of live keys. The existing `W13-AUDIT-JSONL` redaction only covers the dispatch‑path audit rows; the backup tarball is a separate untracked blob. We need to redact all 7 secret patterns from every file archived in a backup, and SHA256‑verify the archive before restore.
- **Acceptance criteria**:
  - `harness backup` walks every file in the backup set, runs the same `redact_secrets()` regex set from `audit.py`, writes a redacted copy, then archives.
  - `harness backup restore` refuses to restore unless a stored SHA256 hash (in `~/.harness/backup/manifest.sha256`) matches the archive.
  - Test: backup a directory containing a fake `KIMI_API_KEY=sk-abc` → restore yields a file with `SK-ABC` (redacted) and manifest hash matches.
  - Known issue: `KIMI_API_KEY` env var itself is not in the backup (it’s env), but if any config file stores it (e.g., `.env`), that gets redacted.
  - The old dead Kimi key from the terminated account is **already** in any backup taken before today’s rotation; the row must include a one‑time cleanup step to re‑backup or instruct the operator to delete old backups.

---

#### 3. W14-KEY-ROTATION-PROCEDURE
- **Title**: Documented key‑rotation playbook + `harness env rotate` helper
- **Estimated effort**: **S** (2h)
- **Why this row, by YOUR lens**: Kimi terminated our account. The operator now has to figure out: (a) how to generate a new key, (b) where to set `KIMI_API_KEY`, (c) how to safely remove the old key from backups and audit logs, (d) how to verify the new key works. Without a playbook, the operator (non‑technical for some work) may leave the dead key in the backup or accidentally commit the new key to a repo. A `harness env rotate <engine>` verb that walks through these steps — including a validation probe, a prompt to delete old backups, and a fingerprint of the new key’s first dispatch — makes rotation a 30‑second ritual instead of a 30‑minute headache.
- **Acceptance criteria**:
  - `harness env rotate kimi` prints step‑by‑step: “1. Create new Kimi key at https://kimi.com/code … 2. Set KIMI_API_KEY env var … 3. Run `harness engines --health` to verify … 4. Run `harness backup` to store a redacted copy without old key … 5. Review `harness audit verify` after rotation”.
  - After step 3, the command automatically runs a probe and reports `kimi: up` or `kimi: auth-failed`.
  - A new `~/.harness/keys_rotated.jsonl` record logs the rotation event (engine name, timestamp, fingerprint of new key [HMAC‑sha256 of key], old‑key fingerprint if available) — no plaintext key stored.
  - Test: `harness env rotate` with a mock engine prints expected prompts and creates a valid rotated‑key log entry.

### Rows you’d DROP from CURRENT_PLAN.md’s Week 2/Week 3 sections

- **CI doc‑doc‑sync gate** (Week 2, ~1h) — This is a docs‑consistency check. Through a security lens, doc drift has zero blast radius on secret leakage, integrity, or audit. If the operator is solo and the README will be updated when they need it, this is a time sink that delays the three rows above. **Drop it.**
- **Schema versioning** (Week 3, S) — Nice‑to‑have for future data‑structure changes, but the current `audit.jsonl` schema is stable and the HMAC chain we propose will embed a schema version anyway. Defer until the first schema change actually lands.
- **`harness commands --did-you-mean`** (Week 3, S) — Frivolous UX. Zero security value. Operator can type `harness` to see the list.
- **Hallucination test harness** (Week 3, S) — Not a security concern. Defer indefinitely.

### Single most important action this week

**Ship `W15-AUDIT-LOG-CHAIN-OF-INTEGRITY` before you even clean up the Kimi dead key — because without it you can’t prove whether the audit trail was tampered with between the termination and today.**

### Confidence in your own recommendation (0.0–1.0)

**0.90** — The Kimi incident perfectly validates the need for backup redaction and a rotation playbook, and the audit‑log chain addresses the most glaring forensic gap. My confidence would drop to 0.6 if the operator reveals that `~/.harness/` itself is on an immutable filesystem or if a prior audit‑log integrity scheme already exists (it doesn’t, per the codebase). It would rise to 0.95 if a quick prototype of the HMAC chain is written this week and passes a tamper test.

### What this lens systematically MISSES

This lens obsesses over detectability and recoverability of secret compromise but **underweights operational velocity** — the operator may need to ship new features or fix bugs next week, not build a forensic chain. A **Productivity/Operations** persona would likely swap my #1 row for something like `W13-INSTALL-VERIFY` follow‑ups or CLI polish, and would drop the HMAC chain as premature. Their perspective should be heard before committing heavy engineering time.