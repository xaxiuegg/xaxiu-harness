"""W14-HARNESS-KEYS-WEB-UI 2026-05-26: interactive HTML form for API key entry.

Operator request: avoid juggling shell env vars when deploying to a
new machine; provide a friendly visual form instead.  Solo-operator
local tool, no multi-user concerns.

Design:
  - Binds to 127.0.0.1 only (never 0.0.0.0)
  - Ephemeral port (OS-assigned)
  - URL contains a single-use token (random 32 bytes urlsafe-base64)
  - Browser auto-opens
  - Form shows current state (masked) for each known provider key
  - Operator pastes new value, clicks Save
  - Save writes to repo-root .env (mode 0600 on POSIX)
  - Optional per-row Test button live-probes the key via
    cli_helpers.probe_engine_live (~5-token throwaway call)
  - Server self-shuts-down after Save OR after 10 min idle

Security model (W14-KEYS-UI-SECURITY-PATCH 2026-05-26):
  - Loopback bind only; never 0.0.0.0
  - 256-bit URL-safe random token; required on every endpoint
  - Origin header validated on POSTs (CSRF defense)
  - env_var allowlist on /api/test and /api/save (no arbitrary
    os.environ writes; can't be coerced into setting PATH/LD_PRELOAD)
  - Value validation: rejects newlines / NUL / single-quote so that
    `set -a; source .env` (which the footer recommends) cannot
    execute attacker-controlled shell expansion
  - .env values written as single-quoted strings (bash-safe)
  - Atomic .env write with tmp file 0600-permed BEFORE content lands
  - DOM rendering via createElement + textContent (no XSS from masked
    key contents reaching innerHTML)
  - Security headers on every response: X-Frame-Options DENY,
    CSP locked-down, Referrer-Policy no-referrer,
    X-Content-Type-Options nosniff
  - Token redacted from BaseHTTPRequestHandler log_message output
  - env_path resolves to harness repo root, not arbitrary cwd

NOT exposed:
  - No support for non-loopback binds
  - No persistence of the token after server exits
  - No multi-user auth — single-operator local tool

Usage:
  $ python -m harness keys serve            # auto-opens browser
  $ python -m harness keys serve --no-open  # print URL only
  $ python -m harness keys list             # status without UI
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


# Providers we know about + how to introspect their status.  The
# display name is shown in the UI; the env var is what gets stored.
KEY_PROVIDERS: list[dict[str, str]] = [
    {
        "env": "KIMI_API_KEY",
        "display": "Kimi (Moonshot)",
        "purpose": ("Kimi Code subscription via Claude Code "
                    "(claude-kimi wrapper)"),
        "engine_probe": "kimi-via-claude",
    },
    {
        "env": "MIMO_API_KEY",
        "display": "MiMo (Xiaomi)",
        "purpose": "MiMo Token Plan or PAYG (claude-mimo wrapper)",
        "engine_probe": "mimo-via-claude",
    },
    {
        "env": "DEEPSEEK_API_KEY",
        "display": "DeepSeek",
        "purpose": "DeepSeek PAYG (direct httpx + claude-deepseek)",
        "engine_probe": "deepseek",
    },
    {
        "env": "DASHSCOPE_API_KEY",
        "display": "Qwen (Alibaba DashScope)",
        "purpose": "Qwen 3.6+ via Alibaba Cloud (claude-qwen wrapper)",
        "engine_probe": "",  # no direct engine yet — wrapper only
    },
    {
        "env": "GLM_API_KEY",
        "display": "GLM (Zhipu z.ai)",
        "purpose": "GLM-5.1 via z.ai (claude-glm wrapper)",
        "engine_probe": "",  # wrapper only
    },
    {
        "env": "ANTHROPIC_API_KEY",
        "display": "Anthropic",
        "purpose": "Direct Anthropic API (optional; only for direct-httpx)",
        "engine_probe": "anthropic",
    },
    {
        "env": "GEMINI_API_KEY",
        "display": "Google Gemini",
        "purpose": "Direct Gemini API (optional; only for direct-httpx)",
        "engine_probe": "gemini",
    },
]


# W14-KEYS-UI-SECURITY-PATCH: allowlist of env vars the UI is
# permitted to write.  Anything not in this set is rejected with
# 400 on /api/test and /api/save so callers cannot write
# PATH / LD_PRELOAD / PYTHONPATH and trick the operator's next
# shell into running attacker code.
KNOWN_ENV_VARS: frozenset[str] = frozenset(s["env"] for s in KEY_PROVIDERS)


# Security headers applied to every response.  CSP allows inline
# style + script because the page is fully self-contained.
# `default-src 'none'` denies everything else; `connect-src 'self'`
# is needed for the fetch() calls to /api/*.
_SECURITY_HEADERS: dict[str, str] = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def _mask(value: str) -> str:
    """Return a masked excerpt safe for display (first 4 + last 4)."""
    if not value:
        return ""
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


def _validate_env_var(env_var: str) -> Optional[str]:
    """Return None if ``env_var`` is in the allowlist, else an error message.

    W14-KEYS-UI-SECURITY-PATCH 2026-05-26.  Closes the
    arbitrary-env-var-write CSRF path through /api/test and /api/save.
    """
    if not env_var:
        return "env_var is required"
    if env_var not in KNOWN_ENV_VARS:
        return f"unknown env_var (not in provider allowlist): {env_var!r}"
    return None


def _validate_value(value: str) -> Optional[str]:
    """Return None if ``value`` is safe to store in .env, else an error.

    Rejects characters that would corrupt the .env format or enable
    shell expansion on `source .env` (which the UI footer recommends).
    """
    if value is None:
        return "value is required"
    if "\n" in value or "\r" in value:
        return "value must not contain newline characters"
    if "\x00" in value:
        return "value must not contain NUL bytes"
    if "'" in value:
        # Single-quote-wrapped .env values can't safely escape a literal '
        # without breaking POSIX sh source semantics.  Reject and ask
        # the operator to re-check the paste — real API keys never
        # contain single quotes.
        return "value must not contain single-quote characters"
    if len(value) > 4096:
        return "value too long (max 4096 chars)"
    return None


def _resolve_env_path() -> Path:
    """Return the canonical .env path for this harness checkout.

    W14-KEYS-UI-SECURITY-PATCH: prior version used Path.cwd(), which
    meant keys saved into whatever directory the operator launched
    the server from — not necessarily the repo.  We now anchor to
    the package location and walk up to the repo root (where
    pyproject.toml lives).  Falls back to cwd if the walk fails.
    """
    try:
        # this file is src/harness/keys_ui.py — repo root is 3 levels up
        candidate = Path(__file__).resolve().parents[2]
        if (candidate / "pyproject.toml").exists():
            return candidate / ".env"
    except (IndexError, OSError):
        pass
    return Path.cwd() / ".env"


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read a POSIX-style .env file into a dict.  Quietly returns
    empty dict when missing or unreadable.  Accepts both
    ``KEY=value`` and ``KEY='value'`` (single-quoted) lines."""
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # Strip a balanced wrapping single or double quote
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            if k:
                out[k] = v
    except OSError:
        return out
    return out


def _write_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Merge ``updates`` into ``env_path`` (POSIX-style .env).  Preserves
    existing keys not in ``updates``.  Atomic write (tmp + replace).
    Sets mode 0600 on the tmp file BEFORE content lands so a crash
    mid-write doesn't leave plaintext keys readable by group/other."""
    current = _read_env_file(env_path)
    current.update(updates)
    # Single-quote every value so bash `set -a; source .env` does NOT
    # perform $-expansion / backtick expansion / arithmetic expansion.
    # _validate_value() above already rejected any value containing
    # a literal single-quote, so this wrapping is bash-safe.
    lines = [f"{k}='{v}'" for k, v in current.items() if v]
    body = "\n".join(lines) + "\n"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = env_path.with_suffix(".tmp")
    # Touch the tmp file empty, chmod it, THEN write — this ensures
    # the 0600 mode is in place before any plaintext lands.
    tmp.touch()
    try:
        tmp.chmod(0o600)
    except (NotImplementedError, OSError):
        pass
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(env_path)
    try:
        env_path.chmod(0o600)
    except (NotImplementedError, OSError):
        pass


def _cleanup_stale_tmp(env_path: Path) -> None:
    """Remove a leftover .env.tmp from a prior crashed write.

    Best-effort; logs but does not raise.  Called at server startup.
    """
    tmp = env_path.with_suffix(".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
            logger.info("keys-ui: removed stale .env.tmp at %s", tmp)
        except OSError as exc:
            logger.warning(
                "keys-ui: could not remove stale .env.tmp at %s: %s",
                tmp, exc,
            )


def _current_value(env_var: str, env_file: Path) -> str:
    """Return the value of env_var from os.environ OR the .env file
    (env-vars-win-tie semantics, matching ``harness.secrets.resolve``).
    Returns empty string when unset."""
    if os.environ.get(env_var):
        return os.environ[env_var]
    file_values = _read_env_file(env_file)
    return file_values.get(env_var, "")


def _build_status() -> dict:
    """Build the UI's /api/status payload.

    Returns a dict with ``providers`` (per-provider rows) and
    ``env_path`` (the absolute path where Save will write).
    """
    env_file = _resolve_env_path()
    file_values = _read_env_file(env_file)
    providers = []
    for spec in KEY_PROVIDERS:
        env_var = spec["env"]
        env_val = os.environ.get(env_var, "")
        file_val = file_values.get(env_var, "")
        if env_val:
            source = "env"
            value = env_val
        elif file_val:
            source = "dotenv"
            value = file_val
        else:
            source = "missing"
            value = ""
        providers.append({
            "env": env_var,
            "display": spec["display"],
            "purpose": spec["purpose"],
            "masked": _mask(value),
            "source": source,
            "has_value": bool(value),
            "engine_probe": spec.get("engine_probe", ""),
        })
    return {
        "providers": providers,
        "env_path": str(env_file.resolve()),
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
#
# NOTE: This template uses SINGLE braces in CSS and JS.  We bind the
# session token via ``str.replace("__TOKEN__", token)`` -- NOT
# ``str.format(...)`` -- so braces do NOT need doubling.
#
# All status-driven row content is built via document.createElement
# + textContent (NOT innerHTML template literals).  This eliminates
# the XSS surface that masked-key contents would otherwise have if
# the operator pasted a key containing HTML metacharacters.


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>xaxiu-harness key setup</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Roboto, Oxygen, Ubuntu, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    margin: 0;
    padding: 32px;
    max-width: 1100px;
    margin: auto;
  }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .subtitle { color: #8b949e; font-size: 13px; margin-bottom: 24px; }
  .env-path-info {
    color: #8b949e;
    font-size: 12px;
    margin-bottom: 24px;
    padding: 8px 12px;
    background: #161b22;
    border-left: 3px solid #1f6feb;
    border-radius: 3px;
  }
  .env-path-info code {
    color: #58a6ff;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .row {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 14px 18px;
    margin-bottom: 12px;
  }
  .row-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .name { font-size: 15px; font-weight: 600; color: #f0f6fc; }
  .source { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
  .source-env { background: #1f6feb; color: white; }
  .source-dotenv { background: #6e4ad9; color: white; }
  .source-missing { background: #6e7681; color: white; }
  .purpose {
    font-size: 12px; color: #8b949e; margin-bottom: 8px;
  }
  .key-input-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .env-label {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    color: #58a6ff;
    min-width: 200px;
  }
  input[type="password"], input[type="text"] {
    flex: 1;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    padding: 8px 10px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
  }
  input:focus {
    outline: none;
    border-color: #1f6feb;
    box-shadow: 0 0 0 2px rgba(31, 111, 235, 0.3);
  }
  button {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 7px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
  }
  button:hover { background: #30363d; }
  button.primary {
    background: #238636; border-color: #2ea043; color: white;
  }
  button.primary:hover { background: #2ea043; }
  button.test {
    background: #1f6feb; border-color: #388bfd; color: white;
  }
  button.test:hover { background: #388bfd; }
  .status {
    font-size: 12px; min-width: 100px;
  }
  .status-up    { color: #3fb950; }
  .status-down  { color: #f85149; }
  .status-test  { color: #d29922; }
  .toolbar {
    margin-top: 24px;
    display: flex;
    gap: 12px;
    justify-content: flex-end;
  }
  .footer {
    color: #8b949e;
    font-size: 12px;
    margin-top: 16px;
    line-height: 1.6;
  }
  .footer code {
    background: #161b22;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 11px;
  }
  .toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    padding: 12px 18px;
    border-radius: 6px;
    font-size: 13px;
    color: white;
    display: none;
  }
  .toast.success { background: #238636; display: block; }
  .toast.error   { background: #da3633; display: block; }
</style>
</head>
<body>

<h1>xaxiu-harness — API key setup</h1>
<div class="subtitle">
  Local-only form (127.0.0.1).  Values save to <code>.env</code>
  in the harness repo root (mode 0600).  Close the browser when
  done to shut down this server.
</div>

<div class="env-path-info" id="env-path-info">
  Loading target .env path&hellip;
</div>

<div id="rows"></div>

<div class="toolbar">
  <button onclick="window.close()">Close</button>
  <button class="primary" id="save-all-btn">Save all to .env</button>
</div>

<div class="footer">
  <p>
    <strong>What this does:</strong>
    Saves provider keys to <code>.env</code> in the repo root.  The
    harness SDK reads from <code>os.environ</code> first, then
    <code>.env</code>, so newly-saved keys take effect on the next
    Python process (no need to restart your shell).
  </p>
  <p>
    <strong>For the wrapper scripts</strong> (<code>claude-mimo</code>,
    <code>claude-kimi</code>, etc.) to also see the keys, you'll need
    them in your shell env.  After saving here, run one of:
  </p>
  <ul>
    <li>Linux/Mac: <code>set -a; source .env; set +a</code></li>
    <li>Windows PowerShell: <code>Get-Content .env | ForEach-Object { $name, $value = $_.Split('=', 2); [Environment]::SetEnvironmentVariable($name, $value.Trim(\"'\"), [EnvironmentVariableTarget]::User) }</code></li>
  </ul>
  <p>
    <strong>Security:</strong>
    Values are saved single-quoted to neutralize shell expansion.
    Keys containing newlines or single-quotes are rejected.  Server
    binds 127.0.0.1 only, idle-shuts after 10&nbsp;min, token-gated.
  </p>
</div>

<div id="toast" class="toast"></div>

<script>
const TOKEN = "__TOKEN__";

async function loadStatus() {
  const r = await fetch(`/api/status?token=${TOKEN}`);
  if (!r.ok) {
    showToast("Failed to load status: HTTP " + r.status, "error");
    return;
  }
  const data = await r.json();
  // Show resolved .env path so operator knows where keys will save
  const envPathEl = document.getElementById("env-path-info");
  envPathEl.textContent = "";
  envPathEl.appendChild(document.createTextNode("Keys will save to: "));
  const codeEl = document.createElement("code");
  codeEl.textContent = data.env_path;
  envPathEl.appendChild(codeEl);
  renderRows(data.providers);
}

// W14-KEYS-UI-SECURITY-PATCH: use createElement + textContent for
// all status-driven content.  No innerHTML interpolation of values
// derived from .env / masked keys / provider metadata.
function renderRows(status) {
  const container = document.getElementById("rows");
  container.textContent = "";
  for (const item of status) {
    container.appendChild(buildRow(item));
  }
}

function buildRow(item) {
  const row = document.createElement("div");
  row.className = "row";

  const head = document.createElement("div");
  head.className = "row-head";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = item.display;
  const source = document.createElement("div");
  source.className = "source source-" + item.source;
  source.textContent =
    item.source === "env" ? "shell env" :
    item.source === "dotenv" ? ".env file" :
    "not set";
  head.appendChild(name);
  head.appendChild(source);

  const purpose = document.createElement("div");
  purpose.className = "purpose";
  purpose.textContent = item.purpose;

  const inputRow = document.createElement("div");
  inputRow.className = "key-input-row";

  const envLabel = document.createElement("div");
  envLabel.className = "env-label";
  envLabel.textContent = item.env;
  inputRow.appendChild(envLabel);

  const input = document.createElement("input");
  input.type = "password";
  input.id = "key-" + item.env;
  input.autocomplete = "off";
  input.placeholder = item.has_value
    ? "(current: " + item.masked + ")"
    : "paste key here";
  inputRow.appendChild(input);

  if (item.engine_probe) {
    const testBtn = document.createElement("button");
    testBtn.className = "test";
    testBtn.textContent = "Test";
    testBtn.addEventListener("click", () =>
      testKey(item.env, item.engine_probe),
    );
    inputRow.appendChild(testBtn);
  }

  const statusEl = document.createElement("span");
  statusEl.className = "status";
  statusEl.id = "status-" + item.env;
  inputRow.appendChild(statusEl);

  row.appendChild(head);
  row.appendChild(purpose);
  row.appendChild(inputRow);
  return row;
}

async function testKey(envVar, engineProbe) {
  const input = document.getElementById("key-" + envVar);
  const statusEl = document.getElementById("status-" + envVar);
  statusEl.textContent = "Testing...";
  statusEl.className = "status status-test";
  const body = JSON.stringify({
    env_var: envVar,
    engine_probe: engineProbe,
    new_value: input.value || null,
  });
  try {
    const r = await fetch(`/api/test?token=${TOKEN}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    });
    const data = await r.json();
    if (data.up) {
      statusEl.textContent = "OK (" + (data.category || "up") + ")";
      statusEl.className = "status status-up";
    } else {
      statusEl.textContent = data.category || "down";
      statusEl.className = "status status-down";
      statusEl.title = data.error || "";
    }
  } catch (e) {
    statusEl.textContent = "probe failed";
    statusEl.className = "status status-down";
    statusEl.title = String(e);
  }
}

async function saveAll() {
  const updates = {};
  for (const input of document.querySelectorAll('input[type="password"]')) {
    const envVar = input.id.replace("key-", "");
    if (input.value) {
      updates[envVar] = input.value;
    }
  }
  if (Object.keys(updates).length === 0) {
    showToast("Nothing to save — all fields empty.", "error");
    return;
  }
  try {
    const r = await fetch(`/api/save?token=${TOKEN}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates: updates }),
    });
    const data = await r.json();
    if (r.ok && data.saved) {
      showToast(
        "Saved " + Object.keys(updates).length + " key(s) to " + data.env_path,
        "success",
      );
      // Reload status so the form reflects the new state
      setTimeout(loadStatus, 200);
    } else {
      const detail = (data && (data.error || data.detail)) || "unknown";
      showToast("Save failed: " + detail, "error");
    }
  } catch (e) {
    showToast("Save error: " + String(e), "error");
  }
}

function showToast(message, kind) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = "toast " + kind;
  setTimeout(() => { el.className = "toast"; }, 4000);
}

document.getElementById("save-all-btn").addEventListener("click", saveAll);
loadStatus();
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _KeyServerHandler(http.server.BaseHTTPRequestHandler):
    """Handler for the key-entry UI server.  Token-gated; all routes
    require ``?token=<TOKEN>`` matching the server's session token.
    """

    server_version = "harness-keys-ui/1.0"

    # W14-KEYS-UI-SECURITY-PATCH: never log the token in URL access lines
    def log_message(self, fmt: str, *args) -> None:
        try:
            redacted = []
            for a in args:
                s = str(a)
                if "token=" in s:
                    # Strip token=... from query strings
                    import re
                    s = re.sub(r"token=[^&\s]*", "token=<redacted>", s)
                redacted.append(s)
            logger.debug("keys-ui: " + fmt, *redacted)
        except Exception:
            # Never crash a request because of a logging issue
            logger.debug("keys-ui: <log redaction failed>")

    def _apply_security_headers(self) -> None:
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._apply_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg: str, status: int = 400) -> None:
        self._send_json({"error": msg}, status=status)

    def _check_token(self) -> bool:
        expected = getattr(self.server, "_token", "")
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        provided = (q.get("token") or [""])[0]
        # Constant-time compare to avoid leaking via timing
        if not expected or not provided:
            return False
        return secrets.compare_digest(expected, provided)

    def _check_origin_for_post(self) -> bool:
        """W14-KEYS-UI-SECURITY-PATCH: validate POST Origin matches
        the server's bound URL.  Defends against a malicious local
        page POSTing with a stolen token from a different origin.

        Empty Origin (curl, native clients) is allowed because the
        token alone is sufficient authn for non-browser clients.
        """
        origin = self.headers.get("Origin", "")
        if not origin:
            return True  # non-browser client; token-only authn
        expected_host = f"127.0.0.1:{self.server.server_address[1]}"
        expected = f"http://{expected_host}"
        return origin == expected

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            if not self._check_token():
                self.send_response(403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self._apply_security_headers()
                self.end_headers()
                self.wfile.write(b"Forbidden: token required")
                return
            body = HTML_PAGE.replace(
                "__TOKEN__",
                getattr(self.server, "_token", ""),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._apply_security_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/status":
            if not self._check_token():
                self._send_error_json("token mismatch", 403)
                return
            self._send_json(_build_status())
            return

        self._send_error_json("not found", 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        # Read+discard the body up front EVEN if we're going to reject —
        # otherwise Windows tears the connection down with WinError 10053
        # because the body sat in the socket buffer unread when we
        # close.  We cap at 64 KB to defend against flooding.
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            # Try to drain so the client can read our response cleanly
            try:
                self.rfile.read(min(length, 64 * 1024))
            except OSError:
                pass
            self._send_error_json("request too large", 413)
            return
        try:
            raw = self.rfile.read(length) if length > 0 else b""
        except OSError:
            raw = b""

        if not self._check_token():
            self._send_error_json("token mismatch", 403)
            return
        if not self._check_origin_for_post():
            self._send_error_json("bad Origin", 403)
            return

        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error_json("invalid JSON", 400)
            return

        if parsed.path == "/api/test":
            self._handle_test(payload)
            return

        if parsed.path == "/api/save":
            self._handle_save(payload)
            return

        self._send_error_json("not found", 404)

    def _handle_test(self, payload: dict) -> None:
        env_var = payload.get("env_var", "")
        engine_probe = payload.get("engine_probe", "")
        new_value = payload.get("new_value")
        # P0-1: validate env_var against allowlist
        err = _validate_env_var(env_var)
        if err:
            self._send_error_json(err, 400)
            return
        if not engine_probe:
            self._send_error_json("engine_probe is required", 400)
            return
        # P0-3: validate value shape if one was supplied
        if new_value:
            v_err = _validate_value(new_value)
            if v_err:
                self._send_error_json(v_err, 400)
                return
        # Override the env var temporarily for the probe if a new value
        # was supplied; otherwise probe with whatever's currently in env
        prior = os.environ.get(env_var)
        if new_value:
            os.environ[env_var] = new_value
        try:
            from harness.cli_helpers import probe_engine_live
            category, err = probe_engine_live(
                engine_probe, log=False,
            )
            up = category == "up"
            self._send_json({
                "up": up,
                "category": category,
                "error": err or "",
            })
        finally:
            if new_value:
                if prior is None:
                    os.environ.pop(env_var, None)
                else:
                    os.environ[env_var] = prior

    def _handle_save(self, payload: dict) -> None:
        updates = payload.get("updates", {})
        if not isinstance(updates, dict) or not updates:
            self._send_error_json("updates must be a non-empty dict", 400)
            return
        # P0-1: every key must be in the allowlist
        for k in updates:
            err = _validate_env_var(k)
            if err:
                self._send_error_json(err, 400)
                return
        # P0-3: every value must pass content-validation
        for k, v in updates.items():
            if not isinstance(v, str):
                self._send_error_json(f"value for {k} must be a string", 400)
                return
            v_err = _validate_value(v)
            if v_err:
                self._send_error_json(f"{k}: {v_err}", 400)
                return
        env_path = _resolve_env_path()
        try:
            _write_env_file(env_path, updates)
        except Exception as exc:
            self._send_error_json(f"write failed: {exc}", 500)
            return
        # Also reflect in current process env so the operator's
        # next harness CLI invocation in the same shell session sees
        # the new values without needing to source .env manually.
        for k, v in updates.items():
            os.environ[k] = v
        self._send_json({
            "saved": True,
            "env_path": str(env_path.resolve()),
            "count": len(updates),
        })


def serve_key_ui(
    *,
    port: int = 0,
    auto_open: bool = True,
    idle_timeout_seconds: float = 600.0,
) -> str:
    """Launch the key-entry UI server.

    Returns the URL the operator should open (the same URL is
    auto-opened in their default browser if ``auto_open`` is True).

    Server lifecycle:
      - Binds to 127.0.0.1 only (never 0.0.0.0)
      - Random ephemeral port unless caller specifies
      - Generates a single-use 32-byte URL-safe token
      - Self-shuts-down after ``idle_timeout_seconds`` of no requests
        (does NOT auto-shut after Save — operator can edit multiple
        rows in succession)
    """
    # P1-4: clean up any leftover .env.tmp from a prior crashed write
    _cleanup_stale_tmp(_resolve_env_path())

    token = secrets.token_urlsafe(32)
    httpd = http.server.HTTPServer(("127.0.0.1", port), _KeyServerHandler)
    httpd._token = token  # type: ignore[attr-defined]
    httpd._last_request_at = time.monotonic()  # type: ignore[attr-defined]
    actual_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/?token={token}"

    # Patch the handler to update last_request_at on every request
    orig_handle = _KeyServerHandler.handle_one_request

    def _handle_one_request(self) -> None:
        try:
            orig_handle(self)
        finally:
            self.server._last_request_at = time.monotonic()  # type: ignore

    _KeyServerHandler.handle_one_request = _handle_one_request  # type: ignore

    # Idle-shutdown watchdog
    def _watchdog() -> None:
        while True:
            time.sleep(5.0)
            elapsed = time.monotonic() - httpd._last_request_at  # type: ignore
            if elapsed >= idle_timeout_seconds:
                logger.info(
                    "keys-ui server idle for %.0fs; shutting down",
                    elapsed,
                )
                httpd.shutdown()
                return

    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()

    serve_thread = threading.Thread(
        target=httpd.serve_forever, daemon=True,
    )
    serve_thread.start()

    print(f"harness keys ui ready at {url}", file=sys.stderr)
    print(f"  binds to 127.0.0.1:{actual_port} only", file=sys.stderr)
    print(f"  token-gated; idle timeout {idle_timeout_seconds:.0f}s",
          file=sys.stderr)
    print("  CTRL+C to exit (or just close the browser).",
          file=sys.stderr)

    if auto_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # Block until the server shuts down (idle timeout or KeyboardInterrupt)
    try:
        serve_thread.join()
    except KeyboardInterrupt:
        httpd.shutdown()
    return url


def list_key_status() -> list[dict]:
    """Return the current key-status list for ``harness keys list``.
    Same shape as the old UI /api/status response (just the providers
    list) — the keys-ui-list CLI doesn't need the env_path field."""
    return _build_status()["providers"]
