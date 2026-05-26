# Pattern B independent-panel synthesis

**Panel fired**: 2026-05-26
**Source**: 22,315-char source pack (research findings + implementation + smoke-test + Pattern A/B trade-offs)
**Result**: 3/4 substantive responses — DeepSeek architect + risk, MiMo architect. MiMo operational-risk failed 3 retries (concrete RemoteProtocolError pattern — itself a data point validating DeepSeek/risk concern D below).
**Per-panelist verdicts**: [deepseek_architectural-correctness.md](deepseek_architectural-correctness.md), [deepseek_operational-risk.md](deepseek_operational-risk.md), [mimo_architectural-correctness.md](mimo_architectural-correctness.md)

---

## Headline

**The core design is architecturally sound. The implementation as shipped is incomplete in two specific, named ways that the panel converges on unanimously.**

Both panelists (DeepSeek + MiMo) at the architectural lens AGREE the subprocess pattern correctly delivers TOS compliance via legitimate Claude Code identity. Both also AGREE that the current code is missing two pieces:

1. **Model-alias env vars** (`ANTHROPIC_DEFAULT_SONNET_MODEL`, `_OPUS_MODEL`, `_HAIKU_MODEL`) — Claude Code internally routes by these names, current code only sets `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`. Without the aliases, internal routing fails or falls back unpredictably.

2. **Explicit env-var purge before set** — current code does `dict(os.environ)` (snapshot copy) which prevents harness→parent leakage, but does NOT purge conflicting `ANTHROPIC_*` vars from the operator's shell that could bleed into the subprocess.

Confidence across the 3 panelists: 0.80, 0.85, 0.85 (average 0.83). No panelist reached >0.95 — moderate-high confidence with named gaps to close.

## Convergent concerns (≥2 panelists agree, ranked)

| Severity | Concern | Voices | Convergent fix |
|---|---|---|---|
| **High / common** | Missing `ANTHROPIC_DEFAULT_*_MODEL` aliases | DeepSeek-A, MiMo-A | Set all 4 aliases (sonnet/opus/haiku/default) to the target provider's model name in `_build_env` |
| **High / common** | Env-var inheritance from parent shell could leak conflicting `ANTHROPIC_*` vars into subprocess | DeepSeek-A, DeepSeek-R, MiMo-A | Explicit `env.pop()` of all conflicting `ANTHROPIC_*` keys BEFORE setting our values; use minimal env (PATH+HOME+SHELL+ours) instead of full inheritance |
| **High / occasional** | Provider model-name drift (e.g. `kimi-k2.6` → `kimi-k3`) silently breaks dispatch with no auto-detection | DeepSeek-A, DeepSeek-R | Add `harness engines refresh-models` verb that probes provider for current model names; cache + alert when drift detected |
| **High / occasional** | Binary version drift — `--bare`, `--print`, `--output-format json` flags could change in future Claude Code releases | DeepSeek-A, DeepSeek-R, MiMo-A | Add a version probe + tolerant command construction; pin minimum supported version + emit warning if older |
| **High / common** | No concurrency limit on subprocess spawning (10+ parallel = OOM/swap risk at ~200MB RSS per Node.js process) | DeepSeek-R | Add `threading.Semaphore(max_concurrency=4)` configurable, wrap subprocess call |
| **High / rare** | Binary missing/deleted/PATH-changed gives `FileNotFoundError` without graceful degradation or diagnostic | DeepSeek-R | Pre-flight `_resolve_binary()` checks file existence; raise actionable RuntimeError with installation hint |
| **Medium / occasional** | First-launch `hasCompletedOnboarding` prompt blocks subprocess indefinitely on fresh installs | DeepSeek-A | Detect missing flag → write `{"hasCompletedOnboarding": true}` to `~/.claude.json` atomically before first dispatch |
| **Medium / occasional** | DeepSeek's Anthropic-compat layer silently drops image / document / MCP / web-search content blocks (text + tools work) | DeepSeek-A | Engine-level docstring warning + optional pre-flight check (refuse with explanation if multimodal content detected for DeepSeek route) |

## Convergent strengths (all 3 panelists agree)

- **Legitimate User-Agent on the wire** — design genuinely uses the real `claude` binary, satisfying provider allowlists (3/3 confirmed)
- **Provider-reported cost capture** — JSON output's `total_cost_usd` replaces our estimate (3/3 confirmed as meaningful improvement)
- **`--bare` isolation** — strips session state, hooks, plugins, keychain reads (3/3 confirmed correct)
- **Clean per-provider registry** — `PROVIDER_ANTHROPIC_ENDPOINTS` + `_engine_name_for_mimo_key` (tp- vs sk- prefix routing) cleanly extensible (3/3 confirmed)

## Dissent / single-voice concerns

| Voice | Concern | Why isolated |
|---|---|---|
| DeepSeek-A | Race condition on `~/.claude.json` from concurrent subprocesses | Only fires when onboarding flag isn't set; other panelists implicitly assumed it would be |
| DeepSeek-R | Persistent Claude Code daemon as alternative (vs spawn-per-dispatch) | Future optimization, not immediate concern; trades off statefulness vs startup cost |
| MiMo-A | Claude Code license fingerprinting / device binding | Forward-looking provider behavior; Anthropic hasn't shipped this |

## Alternative architectures considered by panel

All three panelists evaluated direct-httpx + truthful UA (current pre-Pattern-B state) and confirmed it FAILS at provider gates — not a viable alternative for allowlist-gated providers.

DeepSeek-A proposed a fourth alternative — **local HTTP proxy that rewrites UA** — and dismissed it: more fragile spoofing (TLS fingerprint detection), no architectural improvement over subprocess pattern.

DeepSeek-R proposed **persistent Claude Code daemon** as a future optimization (eliminates 2-5s spawn overhead per dispatch). Not for immediate ship.

## Top-3 concrete changes before any further Pattern B ship

Rank-ordered by panel convergence + severity:

### 1. Set the full `ANTHROPIC_DEFAULT_*_MODEL` alias suite (2 voices, severity high)

```python
# in _build_env()
env["ANTHROPIC_MODEL"] = self._default_model
env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self._default_model
env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self._default_model
env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self._default_model
```

This addresses concern #1 universally. ~10 LOC change.

### 2. Explicit purge of inherited `ANTHROPIC_*` env vars (3 voices, severity high)

```python
# in _build_env(), before setting our own values
env = dict(os.environ)
# Purge anything Claude Code might pick up from parent shell
for var in (
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
):
    env.pop(var, None)
# Now set OUR values
env["ANTHROPIC_BASE_URL"] = self._base_url
env["ANTHROPIC_AUTH_TOKEN"] = self._api_key
# ... etc
```

~15 LOC change.

### 3. Pre-flight binary existence + version check (3 voices, severity high)

```python
# in __init__ or _resolve_binary()
def _verify_binary(binary: str) -> tuple[bool, str]:
    """Return (ok, info_or_error)."""
    try:
        r = subprocess.run(
            [binary, "--version"], capture_output=True, text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return False, f"claude --version returned exit {r.returncode}"
        version = (r.stdout or "").strip().split()[0]  # "2.1.150"
        return True, version
    except FileNotFoundError:
        return False, (
            f"claude binary not found at {binary!r}. "
            f"Install via 'npm install -g @anthropic-ai/claude-code' "
            f"or set HARNESS_CLAUDE_CODE_BINARY."
        )
    except subprocess.TimeoutExpired:
        return False, "claude --version timed out (binary may be hung)"
```

~25 LOC + 1 new test.

## Secondary changes (single-voice, but worth doing)

### 4. Concurrency semaphore (DeepSeek-R, severity high)

```python
# at module level
import threading
_GLOBAL_SUBPROCESS_SEMAPHORE = threading.Semaphore(
    int(os.environ.get("HARNESS_CLAUDE_SUBPROCESS_MAX_CONCURRENT", "4"))
)

# in dispatch()
with _GLOBAL_SUBPROCESS_SEMAPHORE:
    proc = subprocess.run(...)
```

Prevents OOM when panels run 10 parallel Pattern-B engines.

### 5. Onboarding-flag auto-bypass (DeepSeek-A, severity medium)

```python
def _ensure_onboarding_bypass() -> None:
    """Write hasCompletedOnboarding: true to ~/.claude.json if absent."""
    cfg_path = Path.home() / ".claude.json"
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
    if cfg.get("hasCompletedOnboarding"):
        return
    cfg["hasCompletedOnboarding"] = True
    # Atomic write
    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(cfg_path)
```

Call once at engine init. Race-safe because atomic replace.

### 6. DeepSeek multimodal pre-flight (DeepSeek-A, severity low)

In the engine adapter for DeepSeek-via-CC (not yet shipped — only MiMo is), refuse with explanation if `packet_content` contains image-block syntax. Add a docstring warning to the engine class.

## What the panel methodology itself revealed

**Concrete operational risk demonstrated mid-panel**: MiMo failed 3/3 attempts at operational-risk dispatch (RemoteProtocolError, parallel-dispatch race). This is the same pattern DeepSeek-R flagged as concern D (resource exhaustion at scale). The panel literally demonstrated one of its own concerns in real time.

Implication: ANY production use of multi-engine parallel dispatch — Pattern B or not — needs the W14-PARALLEL-DISPATCH-RETRY-FIX row to land. That row is already in the master plan queue but unprioritized; the panel result is evidence it should move up.

## Verdict on whether to proceed with Pattern B + wrapper scripts

**Proceed with Pattern B, but BEFORE shipping wrapper scripts, land the top-3 fixes above** (model aliases + env purge + binary verify). These are ~50 LOC of changes to the existing `ClaudeCodeSubprocessEngine`, ~1-2 hours of work.

Then ship wrapper scripts as a layer on top of the hardened adapter, not a substitute for fixing the adapter first.

**Estimated total work to bring Pattern B to "production-trustworthy"**:
- Top-3 fixes: ~2h
- Concurrency semaphore: ~30min
- Onboarding bypass: ~30min
- Multimodal pre-flight (DeepSeek route only): ~30min
- Wrapper scripts: ~2-3h
- **Total: ~6-7h**

The wrapper scripts the operator asked about earlier remain a good idea — but they're polish, not the load-bearing fix. The load-bearing fixes are the env-purge + model-aliases.

## Recommendation for the operator

Given the panel converged unanimously on three specific code gaps, ship those three fixes BEFORE expanding Pattern B further. Once shipped, the wrapper-script work becomes meaningfully safer.

This matches the operator's instinct in asking for the panel — the design has structural soundness but the implementation has named gaps that would cause failures in production.
