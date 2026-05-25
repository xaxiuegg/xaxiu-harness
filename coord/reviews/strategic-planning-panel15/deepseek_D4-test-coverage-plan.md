# D4-test-coverage-plan — Panel Response

## 1. Lens-specific findings

### Finding 1: Zero test coverage exists for the SDK auto-default heuristics (Tier 1–3 shifts)

The bloat audit proposes auto-pick `lens-set` from file extension and auto-pick `max_tokens` from prompt length. These heuristics are **untested for failure modes**. The source pack states: *“Auto-pick `lens-set` from file extension (`.py` → code-review, `.md` → doc-review, `.pdf` → default)”* with risk: *“None — explicit override still works.”* That conclusion is false. The heuristics can silently misclassify inputs (e.g., a `.py` file with embedded Markdown docstrings → wrong lens; a 50‑token prompt classified as “complex” → wasted 8k tokens). No test checks:
- What happens when the heuristic chooses a lens that does not exist for that engine?
- What happens when the `max_tokens` heuristic returns a value exceeding engine ceiling?
- Does the heuristic log the choice so the operator can audit?
**Every auto-default must have a failure-mode test before it ships.**

### Finding 2: Security tests are completely missing for all backup and secrets rows

The source pack says of `W13-BACKUP-ENCRYPTION`: *“Add AES-256 encryption of the .tar.gz body using a key derived from DPAPI (Windows) or system keyring (Linux/Mac).”* There is **no mention of testing**: key derivation failure, corrupted archive, missing key at restore time, path traversal within the encrypted tar. The same is true for `W13-SECRETS-ROTATION`: the runbook outlines a manual procedure but no tests exist for the CLI verb. The cross‑engine panel already flagged this risk (DeepSeek quote: *“W13-BACKUP-RESTORE snaps .harness/ which likely contains API keys… no discussion of encryption at rest”*). **These rows cannot ship without a dedicated security test suite.**

### Finding 3: Regression test suite (2197 tests) has high coverage of existing API but zero coverage of the planned SDK shifts

The master audit states *“Tests: 2179+ green (no regressions across all 12 commits)”*. Good. But there is **no regression test that runs the full suite after applying the auto‑default heuristics** (e.g., `HARNESS_AUTO_LENS=true`). The entire suite passes with today’s explicit‑override behavior. As soon as the heuristics activate, a hidden regression could break `harness review` for certain file types. **We need a CI step that runs the full suite with auto‑defaults enabled** (simulating the new behavior) before any heuristic ships.

### Finding 4: Test‑to‑implementation ratio estimates are missing from the plan entirely

The horizon‑c plan lists effort in S/M/L but never separates test‑writing from implementation. For an internal tool, tests are at least as important as the feature because the operator is the sole maintainer. Rows like `W13-BACKUP-ENCRYPTION` (implementation ~3h) will likely require **4–5h of testing** (key derivation on multiple platforms, round‑trip corruption, key‑not‑available scenarios). That is a ratio >1.5×, which I classify as **high risk** because if testing is skipped due to time pressure, the backup‑restore story becomes unreliable.

### Finding 5: The `harness whoami` mitigation (bloat audit Part 4) is a test of the CLI rather than a production feature, but its own test plan is trivial

The bloat audit says: *“`harness whoami` — single command listing engines/lens-sets/verbs available NOW — effort S, 1-2h”*. The test plan is straightforward (happy path, each engine/lens/verb appears, empty state). However, the **integration test** (does the output actually match the runtime state?) requires mocking the full dispatcher. This is a good candidate for a quick ship because test effort is ≤1h.

---

## 2. Recommended SHIP list (top 4 rows to do FIRST)

### 1. W13‑BACKUP‑ENCRYPTION — with a mandatory security test suite

**Why first:** Backup protects against data loss. Encryption is the single point of trust. Ship the encryption *after* writing the following tests (estimate test effort 5h, implementation 4h → ratio 1.25×, still high but justified).

**Test cases (by category):**

- **Happy‑path unit:**
  - `test_backup_create_encrypted_archive`: creates a `.tar.gz.aes` file; assert it is not a plain tar.
  - `test_backup_roundtrip_encrypt_decrypt`: create encrypted backup → restore → assert all files match original (excluding .env and worktrees).
  - `test_backup_manifest_cleartext`: list backups before decrypt → shows metadata without key.

- **Failure‑mode:**
  - `test_backup_decrypt_wrong_key`: restore with an incorrect key → raises `DecryptionError`, archive untouched.
  - `test_backup_decrypt_corrupted_archive`: damage bytes in archive → restore raises `CorruptedArchiveError`.
  - `test_backup_key_derivation_fails`: if DPAPI is unavailable and no keyring → graceful error, no crash.

- **Integration:**
  - `test_backup_encrypt_decrypt_cli`: `harness backup create` → `harness backup restore` completes without error.
  - `test_backup_encryption_uses_derived_key`: mock key derivation → confirm the correct AES key is used.

- **Security:**
  - `test_backup_encryption_path_traversal`: tar with `../../etc/passwd` → restore rejects.
  - `test_backup_encryption_key_never_in_archive`: grep archive for any substring of the key → assert not present.

### 2. W13‑SECRETS‑ROTATION — test the entire rotate‑test‑rollback loop

**Why second:** Key rotation is manual today; the automated CLI verb reduces operator error. But if the verb fails, the operator could lose access. Test effort 3h, impl 3h → ratio 1.0×, manageable.

**Test cases:**
- **Happy‑path:**
  - `test_secrets_rotate_updates_env`: after rotate, `harness secrets source kimi` returns `dotenv`.
  - `test_secrets_rotate_tests_connectivity`: mock engine dispatch → verify `harness secrets rotate` calls a test dispatch before updating.
- **Failure‑mode:**
  - `test_secrets_rotate_rollback_on_failure`: test dispatch fails → `rotate` reverts `.env` to previous value, no orphan.
  - `test_secrets_rotate_key_already_expired`: if key is invalid before rotate → rotate detects and suggests getting new key.
- **Integration:**
  - `test_secrets_rotate_end_to_end`: create temp `.env` with a working key → rotate to a real new key → subsequent dispatch succeeds.

### 3. Tier 1 Shift A (auto‑pick lens‑set from file extension) — with override and logging tests

**Why third:** Low effort (30min impl, 2h test) but high impact on operator experience. Must have failure‑mode tests before ship.

**Test cases:**
- **Happy‑path:**
  - `test_auto_lens_py`: file `.py` → `code-review` selected.
  - `test_auto_lens_md`: `.md` → `doc-review`.
  - `test_auto_lens_pdf`: `.pdf` → `default`.
- **Failure‑mode:**
  - `test_auto_lens_unknown_extension`: `.xyz` → falls back to `default` with warning.
  - `test_auto_lens_override_explicit`: `--lens-set code-review` on a `.md` → explicit flag wins.
  - `test_auto_lens_logged`: dispatch audit record includes `auto_lens_used` field.
- **Regression:**
  - `test_regression_full_suite_with_auto_lens_enabled`: runs entire 2197‑test suite with `HARNESS_AUTO_LENS=true` and asserts zero failures.

### 4. W13‑AUDIT‑JSONL — test append, rotation, and corruption resilience

**Why fourth:** This row (every dispatch appends to `audit.jsonl`) is the foundation for all future forensic analysis and for the `operator‑reads‑what‑happened` use case. Test effort 2h, impl 2h → ratio 1.0×.

**Test cases:**
- **Happy‑path:**
  - `test_audit_jsonl_append_on_dispatch`: after `harness.dispatch`, the line appears in `~/.harness/audit.jsonl`.
  - `test_audit_jsonl_correct_fields`: each line contains `dispatch_id`, `engine`, `tokens_in`, `tokens_out`, `cost`, `timestamp`.
- **Failure‑mode:**
  - `test_audit_jsonl_append_when_file_missing`: if file absent, create it (parent dirs auto‑created).
  - `test_audit_jsonl_rotation`: when file >10MB, archive and start new file (no data loss).
  - `test_audit_jsonl_corrupted_line`: if a line is truncated (power loss), reader skips it and continues.
- **Security:**
  - `test_audit_jsonl_no_secrets`: scrub `KIMI_API_KEY` or other env vars before writing (audit line must never contain raw keys).

---

## 3. Recommended DROP list (top 3 rows to NOT do)

### 1. W13‑PLUGIN‑SANDBOX‑PLAN (decision row)

**Why drop:** This is a decision row for Wave 15. The internal‑tool framing explicitly says *“trusted authors”*. The source pack says: *“accept the risk and document it (since internal-tool = trusted authors).”* Spending 2–3h on a sandbox decision for something that won’t be implemented for weeks is distraction. If the tool remains internal, the decision is trivial. Drop until Wave 15 actually starts.

### 2. W13‑VPS‑OBSERVER‑NAT‑PLAN (decision row)

**Why drop:** Wave 17 (VPS hardening) is at the end of the roadmap. The NAT problem is well‑known and the plan already lists alternatives (laptop polls VPS, webhook). No code is being written now. Drop; revisit only when VPS observer work begins.

### 3. Tier 3 Shift D (auto‑close low‑severity observer flags after 7d)

**Why drop:** The bloat audit lists this as “MED — could lose signal”. For an internal tool, losing low‑severity flags is worse than having them stale. The operator can manually dismiss. The test effort (1h) is not worth the risk of missing a pattern that builds up over weeks. Drop.

---

## 4. Recommended ADD list (top 2 new rows)

### 1. `W13‑TEST‑INFRASTRUCTURE‑FOR‑AUTO‑DEFAULTS`

**Pitch:** Create a dedicated test helper that runs every SDK dispatch heuristics (auto lens, auto max_tokens, auto retry, cost pre‑check) against a matrix of inputs and asserts the heuristic output is logged, overridable, and auditable. This is a meta‑test that validates the “visible + overridable + auditable” trio from the bloat audit. Without it, every future auto‑default ships untested for hidden behavior.

**Effort:** M (4h) — one‑time investment that covers all future auto‑defaults.

### 2. `W13‑REGRESSION‑GATE‑FOR‑SDK‑SHIFTS`

**Pitch:** Add a GitHub Actions workflow that runs the full test suite TWICE per PR: once with `HARNESS_AUTO_DEFAULTS=0` (today’s behavior) and once with `HARNESS_AUTO_DEFAULTS=1` (proposed new behavior). The gate fails if any test fails in either mode. This prevents the auto‑defaults from breaking existing workflows.

**Effort:** S (1h) — one YAML change plus a script to set env vars.

---

## 5. Single most important recommendation

> **Before writing any code for Tier 1–3 shifts or Wave 13 rows, write and execute a complete test plan for `W13‑BACKUP‑ENCRYPTION` and `W13‑SECRETS‑ROTATION`, including the security test cases enumerated above — because these two rows protect the operator from catastrophic data loss, and they have **zero test coverage today** according to the source pack.**