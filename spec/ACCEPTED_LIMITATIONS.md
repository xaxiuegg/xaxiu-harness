# xaxiu-harness — Accepted Limitations (v0.x dev mode)

This document captures security limitations explicitly accepted for the v0.x
development series. Each limitation has a planned resolution path tied to a
specific later version. v1.0 production release must close every item or
escalate to operator decision.

---

## ACCEPT-1: File mode 0600 is largely advisory on Windows

**Affected modules:**
- `src/harness/state/files.py::_set_mode_0600`
- `src/harness/state/jsonl_log.py::_set_restricted_permissions`
- `src/harness/secrets/dpapi.py::_set_secret_file_perms`

**Detection:** Wave 2B batch-1 security audit (2026-05-17) flagged that
`os.chmod(path, 0o600)` on Windows honors only the read-only bit; it does NOT
restrict access from other local user accounts. This is the standard Python
stdlib behavior — Windows ACLs require a different API.

**Why accepted for v0.x:**
- The pywin32 DACL implementation attempted in earlier Wave 2A iteration was
  rejected as broken (allow-ACE without explicit deny — see Wave 2A audit HIGH-1)
  and as an undeclared dependency (build-breaker on clean install).
- v0.x runs in operator's own single-user dev directory; the threat model is
  primarily "accidental commit of secret to git" (covered by `.gitignore`
  excluding `state/`) and "leak via logs/exceptions" (covered by closed-schema
  jsonl writer + redaction + DPAPI encryption-at-rest for secrets).
- A correct Windows DACL implementation requires `ctypes` calls to advapi32 +
  `SetSecurityInfo` with `SECURITY_DESCRIPTOR` construction, ~80-120 LOC of
  code that benefits from being part of the v1.x signed installer's
  privileged install-time setup rather than runtime per-file calls.

**Resolution path:**
v1.0 signed Windows installer (per v1.1 §5.1) will:
1. Create `state/` directory with explicit DACL granting only the installing
   user (CRYPTPROTECT_LOCAL_MACHINE flag UNSET — same scope as DPAPI).
2. Inherit DACL to all child files created by harness at runtime.
3. `harness install` will re-apply the DACL on every install (idempotent).
4. A separate `_verify_state_perms()` helper runs at start-up and warns if
   DACL has been tampered with.

**Verification check (v0.x):**
None required at runtime; documented in this file. Any audit pass MUST quote
this limitation by ID (ACCEPT-1) when it surfaces the chmod gap.

---

## ACCEPT-2: Inter-process lock on jsonl rotation deferred

**Affected module:** `src/harness/state/jsonl_log.py::rotate_if_needed`

**Detection:** Wave 2B batch-1 audit MED-3/4 noted that rotation has no
inter-process lock between the size-check and the gzip/rename, and uses a
slightly fragile `Path.with_suffix` technique.

**Why accepted for v0.x:**
- v0.x is single-process: only one `harness` invocation writes the jsonl at a
  time. Race conditions require concurrent writers, which the v0.x CLI surface
  does not produce.
- The dashboard server (v0.x+) is a separate process and DOES read the jsonl,
  but reads are tolerant of in-flight rotation (worst case: skip the
  partially-gzipped file for one cycle).

**Resolution path:**
v0.3.x (Wave 3 dashboard) will add `filelock` dependency + portable file
lock around rotate-check + append. Same release introduces multi-process
testing.

---

## ACCEPT-3: Engine `dispatch` broad `except Exception` may bury forensic signal

**Affected module:** `src/harness/engines/concrete.py::*Concrete.dispatch`

**Detection:** Wave 2B batch-1 audit MED-2 noted the broad exception handler
catches `json.JSONDecodeError`, `KeyError`, etc., and labels them all
`"internal"`. The packet-trap detector (Wave 2B.4 engine guards) would benefit
from differentiating these.

**Why accepted for v0.x:**
- Wave 2B.4 (engine guards) has not yet been dispatched. It can add a
  pre-parse wrapper that inspects the raw response BEFORE the broad except
  fires, providing the forensic signal upstream.
- For v0.x manual operation, the bare "internal" label is acceptable; the
  operator can re-run with `--progress` and see the raw httpx stderr.

**Resolution path:**
Wave 2B.4 engine guards will wrap `dispatch()` and inspect the response shape
before it reaches the broad handler. v0.3.x (Wave 3 dashboard) surfaces full
error trace in the decision-archaeology panel (v1.1 §6).

---

## Auditor protocol

When a security audit finds an issue addressed by this document:
- Report the finding as usual with full details.
- Append `(per ACCEPT-N)` to the severity line.
- Treat as LOW for blocking purposes — do not gate Wave dispatch on these.

When a v1.0 release candidate is built, every `ACCEPT-N` MUST be either
resolved (with linked PR) or escalated to operator for explicit re-acceptance.
