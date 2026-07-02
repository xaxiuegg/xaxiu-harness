"""xaxiu-harness CLI.

Cross-project multi-engine LLM dispatch + monitoring tool.

PATH-A-TRIM 2026-05-29: trimmed to the thin ask/proxy/keys core.  The
coord / dashboard / observer / loops / orchestrator machinery was deleted
(recoverable from branch+tag archive/pre-trim-2026-05-29).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import click

from harness.cli_helpers import probe_all_engines
from harness.operator import resolve_operator_config
from harness.operator.flags import OPERATOR_FLAG_NAMES, apply_operator_flags
from harness.state.files import read_engine_health

# Budget primitive (BUDGET-METER)
from harness.budget import (
    DEFAULT_CAP_PATH,
    DEFAULT_LEDGER_PATH,
    export_daily_csv,
    read_ledger,
    summary as budget_summary,
)

# PATH-A-TRIM 2026-05-29: the observer/loops/coord/dashboard/orchestrator
# machinery was deleted (harness retirement to a thin ask/proxy/keys core).
# The lazy observer wrapper functions that lived here existed only for the
# now-removed observer verbs.


@click.group()
@apply_operator_flags
@click.pass_context
def cli(ctx: click.Context, **operator_overrides: object) -> None:
    """xaxiu-harness: dispatch, observe, and retro across LLM engines."""
    ctx.ensure_object(dict)
    cli_overrides = {name: operator_overrides.get(name) for name in OPERATOR_FLAG_NAMES}
    ctx.obj["operator_config"] = resolve_operator_config(
        cli_overrides=cli_overrides,
        env=os.environ,
    )


def _bootstrap_utf8_stdout() -> None:
    """W12-WINDOWS-CP1252-FIX (2026-05-24): force UTF-8 on stdout/stderr.

    The 20-agent operator-review panel found three distinct CLI entry
    points (``preflight``, ``--help``, ``agent init``) crashing with
    ``UnicodeEncodeError`` on Windows console (cp1252) when emitting
    `\\u2192` (->), `\\u03b1` (alpha), or `\\u2713` (check) glyphs.
    Reconfigure stdout/stderr at process entry so click.echo never
    hits cp1252 again.  errors='replace' is a safety belt: if a glyph
    still cannot encode (older Python without reconfigure, or a fd
    redirected to a strict file), the glyph is replaced with '?'
    rather than crashing.

    Safe on POSIX (utf-8 is the default anyway) and on Windows with
    UTF-8 console codepage.  Idempotent.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # piped to a non-TextIOWrapper sink
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Some redirected streams refuse reconfigure; not fatal.
            pass


# W14-TRIM 2026-05-29: the verbs surfaced in the default ``harness --help``.
# Everything else still RUNS (and is listed by ``harness advanced list``) but
# is hidden from default help so the usable core (docs/CORE.md) stands out.
# This is the immediately-usable half of the trim-to-core; the coupled
# machinery (coord/observer/loops/dashboard) is deleted in a separate careful
# refactor.  Over-hiding is low-risk: a hidden verb still works + is discoverable.
_CORE_VISIBLE_VERBS = {
    "ask",
    "ask-history",
    "ask-show",  # cross-vendor compare — the moat
    "proxy",  # OpenAI-compatible endpoint
    "keys",
    "env",
    "env-wizard",  # credentials + guided setup
    "doctor",
    "introspect",
    "engines",  # health + discovery
    "budget",
    "audit",  # cost + forensic ledger
    "capabilities",
    "plan",
    "today",  # surface + orientation
    "advanced",  # browse the hidden verbs
}


def _hide_noncore_verbs() -> None:
    """Hide non-core verbs from the default ``harness --help``.  They still
    run and appear in ``harness advanced list``.  Idempotent; never raises
    (purely cosmetic — must never block the CLI)."""
    try:
        for _name, _cmd in cli.commands.items():
            if _name not in _CORE_VISIBLE_VERBS:
                _cmd.hidden = True
    except Exception:
        pass


def main(*args, **kwargs):
    """Entry point that wraps click with W5-DD top-level HarnessError handler.

    Any ``HarnessError`` that escapes the click verb is routed through
    ``handle_harness_error`` so the operator sees the L5 escalation banner
    (or the L3/L4 one-line summary) instead of click's vanilla traceback.
    Exits with the level-derived exit code (0/0/1/3/4).

    Programmatic callers that catch HarnessError themselves can still call
    ``cli`` directly to bypass this.
    """
    # W12-WINDOWS-CP1252-FIX: force UTF-8 on stdout/stderr before click
    # writes a single byte.  The 20-agent operator-review panel found
    # this was the #1 universal blocker (cp1252 crashes on -> alpha check).
    _bootstrap_utf8_stdout()
    _hide_noncore_verbs()

    from harness.errors import HarnessError, handle_harness_error

    try:
        return cli(*args, **kwargs)
    except HarnessError as exc:
        handle_harness_error(exc, sys_exit=sys.exit)




# PATH-A-TRIM 2026-05-29: spec-register / spec-verify removed — they depended
# on the deleted coord.provenance machinery (part of the coord pipeline).


def _agent_instructions_snippet(
    fmt: str,
    repo_root: Path,
    home_dir: Path,
) -> str:
    """W14-ASK-DOCS 2026-05-27: single source of truth for the agent-
    instructions snippet content.  Used by BOTH ``harness agent-
    instructions`` (which prints) AND ``harness install-agent-
    instructions`` (which appends to ~/.claude/CLAUDE.md).

    Keeping the content in one place prevents the two commands from
    drifting — a prior W14 bug had ``install`` carrying stale
    pre-v0.5.1 3-engine framing while the print verb already used the
    new 3-mode framing.
    """
    if fmt == "claude-md":
        return (
            f"## xaxiu-harness is available\n\n"
            f"Multi-engine LLM + OpenAI-compatible HTTP proxy + agentic "
            f"dispatch toolkit, installed at `{repo_root}`.\n\n"
            f"### Verb cheat-sheet — read this FIRST\n\n"
            f"```\n"
            f"harness introspect                   ← Run in a FRESH session OR when you\n"
            f"                                       need to discover the harness surface.\n"
            f"                                       Single-call snapshot of verbs +\n"
            f"                                       engines + proxy state + doctor.\n"
            f"                                       Skip for focused single-shot tasks\n"
            f"                                       where the cheat-sheet below suffices.\n"
            f'harness ask "..."                    Daily-driver LLM verb.  3 modes:\n'
            f'  ask "..."                         routed (1 engine, ~$0.01-0.05)\n'
            f'  ask "..." --audit                producer→auditor (~$0.05)\n'
            f'  ask "..." --panel                3-engine fanout (~$0.20-0.30)\n'
            f"  ask --rerun <dir> --escalate X    replay + upgrade prior ask\n"
            f"harness ask-history                  List past asks (note the HYPHEN —\n"
            f"                                     `ask history` with a space fires a NEW ask)\n"
            f"harness ask-show <id>                Render one past ask (also hyphenated)\n"
            f"harness proxy start --upstream X     OpenAI-compatible HTTP proxy\n"
            f"                                     on 127.0.0.1:7879.  4 upstreams:\n"
            f"                                     kimi-http (default), deepseek-http,\n"
            f"                                     mimo-via-claude-code,\n"
            f"                                     kimi-via-claude-code (subprocess\n"
            f"                                     upstreams are TOS-compliant for\n"
            f"                                     UA-gated providers like MiMo Token\n"
            f"                                     Plan and Kimi Code subscription —\n"
            f"                                     DO NOT hand-roll a custom shim).\n"
            f"harness proxy upstreams              List all 4 upstreams with details\n"
            f"harness engines describe <name>      Per-engine metadata: protocols,\n"
            f"                                     UA-gating, key prefixes, models,\n"
            f"                                     recommended task classes.\n"
            f"harness engines compatibility-matrix N×M consumption-surface table\n"
            f"harness engines recommend <class>    Empirical routing pick\n"
            f"harness doctor                       7-check traffic-light health table\n"
            f"harness keys serve                   Browser form for API keys\n"
            f"xaxiu-swarm dispatch                 Sibling repo: agentic multi-file\n"
            f"                                     dispatch.  NOT part of this repo;\n"
            f"                                     clone separately if needed.\n"
            f"```\n\n"
            f"Details below.\n\n"
            f"### 1. `harness ask` — daily-driver LLM verb\n\n"
            f'Bare `python -m harness ask "..."` routes through an '
            f"empirical recommender to ONE engine (~$0.01-0.05, ~30s).  "
            f"Cheap enough for routine second opinions; NOT for every "
            f"prompt (you're already an LLM — do the work yourself when "
            f"you can).\n\n"
            f"Three modes + conversational re-ask:\n\n"
            f"```bash\n"
            f'python -m harness ask "..."                  # routed, 1 engine ~$0.01-0.05\n'
            f'python -m harness ask "..." --task <class>   # routed by task class\n'
            f'python -m harness ask "<claim>" --audit      # 2 engines: producer + auditor ~$0.05\n'
            f'python -m harness ask "..." --panel          # 3 engines parallel ~$0.20-0.30\n'
            f"python -m harness ask --rerun <dir>            # re-ask question from prior ask dir\n"
            f"python -m harness ask --rerun <dir> --escalate audit\n"
            f"                                              # upgrade routed → audit on the same question\n"
            f"```\n\n"
            f"**When in doubt, default to bare `ask`.**  ~90% of "
            f"questions are correctly answered by routed-1-engine.  "
            f"Reach for `--audit` only when you (or the user) have just "
            f"committed to a non-obvious factual claim worth sanity-"
            f"checking by a different engine.  Reach for `--panel` only "
            f"when cross-vendor diversity genuinely matters (rare).\n\n"
            f"Task classes: `default | latency | verbose | cost | "
            f"high-volume | multimodal | audit`.  "
            f"`harness engines recommend <class>` shows the pick + "
            f"rationale.\n\n"
            f"**`--audit` is the hallucination self-check primitive.**  "
            f"When you're about to commit to a non-obvious factual "
            f"claim that downstream decisions hinge on, audit it first: "
            f'`harness ask "<claim>" --audit --output /tmp/audit` and '
            f"inspect `/tmp/audit/summary.json` for "
            f"`verdict.verdict ∈ {{PASS, PARTIAL, FAIL, UNKNOWN}}`.\n\n"
            f"  *Decision pattern:* skim the routed engine's answer "
            f"BEFORE deciding to escalate — escalation is most valuable "
            f"when the producer makes specific falsifiable claims that "
            f"could be wrong.  A vague or hedged answer rarely benefits "
            f"from audit; a confident-sounding numbered recommendation "
            f"often does.\n\n"
            f"  *Verdict semantics:* the verdict applies to the "
            f"**producer's answer**, not to the input claim.  If you "
            f"asked the producer to fact-check a wrong claim and the "
            f"producer correctly refuted it, the auditor returns PASS "
            f"(refutation is sound).  Always read the producer's "
            f"answer + the auditor's `corrections`/`missed` fields, "
            f"not just the top-level verdict.\n\n"
            f"**`--panel` is the 3-engine fanout** (was the bare default "
            f"before v0.5.1; now opt-in).  Use only for genuinely cross-"
            f"cutting design crossroads where vendor diversity matters.\n\n"
            f"**When NOT to reach for `harness ask`**:\n"
            f"- Routine implementation work (write the code yourself)\n"
            f"- Factual lookups (WebSearch / WebFetch are faster + free)\n"
            f"- Multi-file refactors / agentic dispatch (use xaxiu-swarm, "
            f"see #3 below)\n"
            f"- Sub-routine LLM calls from external tools (use the "
            f"proxy, see #2 below)\n\n"
            f"**`--research <path>` shifts synthesis to a cheaper engine:** "
            f"when answering a question that needs CURRENT info, do the "
            f"WebSearch in your own context (Claude Code has WebSearch + "
            f"WebFetch built-in), dump the findings to a markdown file, "
            f'then run `harness ask "<question>" --research <findings.md>`.  '
            f"The harness prepends the research as context and routes the "
            f"synthesis to a Pattern B engine (cheap, ~$0.02) instead of "
            f"making YOU (often Opus, expensive) do the synthesis.  "
            f"Saves a copy of the research to the output dir's "
            f"`research.md` for traceability.  Composes with `--audit` "
            f"(producer sees research; auditor sees the synthesis).\n\n"
            f"**Auto-audit heuristic for your own claims:** when you "
            f"(the agent) are about to commit to a specific, non-obvious, "
            f"falsifiable factual claim — model versions, API behavior, "
            f"protocol shapes, library invariants, project history — "
            f"and your confidence is below ~80%, OR a downstream "
            f"decision (a PR, a Slack post, a config change) hinges on "
            f"the claim being right, wrap it in `--audit` BEFORE the "
            f"user sees it.  This costs ~$0.05 and ~60s.  It is "
            f"strictly cheaper than the wrong-path pivot caused by a "
            f"hallucinated detail.  The canonical case where this "
            f"would have saved real time: a recent agent claimed "
            f'"MiMo speaks Anthropic protocol only" based on partial '
            f"source reading; an `--audit` call at the moment of the "
            f"claim would have surfaced the dual `/v1` + `/anthropic` "
            f"surfaces in under a minute.\n\n"
            f"Outputs land at `{repo_root}\\coord\\reviews\\ask-"
            f"<ts>-<slug>\\` with `question.md`, per-engine `*.md`, "
            f"`packet.md` (panel/audit only), and `summary.json` (with "
            f"`mode` field).\n\n"
            f"### 2. `harness proxy` — OpenAI-compatible HTTP endpoint\n\n"
            f"For sub-routine LLM calls from third-party tools that "
            f"want an OpenAI-compatible `/v1/chat/completions`:\n\n"
            f"```bash\n"
            f"python -m harness proxy upstreams                       # see all 4 upstreams\n"
            f"python -m harness proxy start                           # Kimi (default)\n"
            f"python -m harness proxy start --upstream deepseek-http  # direct DeepSeek\n"
            f"python -m harness proxy start --upstream mimo-via-claude-code\n"
            f"                                                        # MiMo TOS-compliant\n"
            f"python -m harness proxy status   # pool / in-flight stats\n"
            f"python -m harness proxy stop\n"
            f"```\n\n"
            f"Then point the consuming tool at "
            f"`OPENAI_API_BASE=http://127.0.0.1:7879/v1`.  Multi-key "
            f"pool + circuit breaker apply.  Four upstreams: "
            f"`kimi-http` (default), `deepseek-http` "
            f"(direct HTTP); `mimo-via-claude-code`, "
            f"`kimi-via-claude-code` (TOS-compliant Claude Code "
            f"subprocess for User-Agent-gated providers).  **DO NOT "
            f"hand-roll a custom shim for MiMo Token Plan or Kimi Code "
            f"subscription — the subprocess upstreams already do it "
            f"TOS-compliantly.**\n\n"
            f"### 3. xaxiu-swarm (sibling repo) — agentic dispatch\n\n"
            f"For multi-file refactors + multi-turn tool use across a "
            f"codebase, the sibling project handles it.  Install at "
            f"`https://github.com/xaxiuegg/xaxiu-swarm` then:\n\n"
            f"```bash\n"
            f"xaxiu-swarm dispatch --backend kimi \\\n"
            f"  --deliverable /path/to/output.md \\\n"
            f"  --add-dir /path/to/repo \\\n"
            f"  --context-file CLAUDE.md \\\n"
            f"  --timeout 420 \\\n"
            f"  --packet packet.md\n"
            f"```\n\n"
            f"Backends: `kimi` (CLI, agentic), `kimi-api`, `deepseek`, "
            f"`mimo` (TOS-compliant via Claude Code subprocess).  "
            f"NOT required for `harness ask` or `harness proxy` — clone "
            f"only if you need agentic multi-file work.\n\n"
            f"### 4. Engine discovery — query before guessing\n\n"
            f"**Before making factual claims about an engine (protocol "
            f"surfaces, key prefixes, UA gating, model lineup), query "
            f"the metadata.  This is a 1-call answer to questions that "
            f"used to require reading 100+ lines of source.**\n\n"
            f"```bash\n"
            f"python -m harness engines describe <name>          # full metadata for one engine\n"
            f"python -m harness engines describe <name> json     # JSON output\n"
            f"python -m harness engines compatibility-matrix     # N×M engine × consumption surface\n"
            f"python -m harness engines recommend <task-class>   # empirical routing pick\n"
            f"```\n\n"
            f"The canonical example: "
            f"`harness engines describe mimo-via-claude` answers "
            f'"does MiMo speak OpenAI or Anthropic?" in 1 call.  '
            f"Answer: BOTH — see the dual `protocol_surfaces` field.  "
            f"Source-spelunking is no longer required for this class of "
            f"question.\n\n"
            f"### 5. Past asks — `harness ask-history` + `ask-show`\n\n"
            f"**⚠ Note the hyphen:** the verbs are `ask-history` and "
            f"`ask-show` as single words.  Typing `harness ask history` "
            f"(with a space) does NOT list past asks — it fires a "
            f"BRAND NEW routed ask with `history` as the question.  A "
            f"fresh agent in a 2026-05-28 test fell into exactly that "
            f"trap; the hyphen is load-bearing.\n\n"
            f"Browse the forever-record of past `harness ask` outputs "
            f"without leaving the CLI:\n\n"
            f"```bash\n"
            f"python -m harness ask-history --last 10            # last 10 asks\n"
            f"python -m harness ask-history --mode audit         # audit only\n"
            f"python -m harness ask-history --verdict FAIL       # past failures\n"
            f"python -m harness ask-history --format json | jq   # programmatic\n"
            f"python -m harness ask-show <ask-id>                # render one\n"
            f"```\n\n"
            f"Pairs with `harness ask --rerun <dir>` (above): use "
            f"`ask-history` to find an id, then `ask --rerun` to re-ask "
            f"with the same question + optionally upgrade the mode via "
            f"`--escalate audit` or `--escalate panel`.\n\n"
            f"Idiomatic chain (no copy-paste needed):\n\n"
            f"```bash\n"
            f"# Run routed; the stdout prints '  → review at <PATH>' on success.\n"
            f'python -m harness ask "..."\n'
            f"# Then escalate using the path just printed:\n"
            f'python -m harness ask --rerun "<PATH from previous stdout>" --escalate audit\n'
            f"```\n\n"
            f"### Start here — `harness introspect`\n\n"
            f"**The single command a fresh session should run first.**  "
            f"`python -m harness introspect --format json` returns one "
            f"structured snapshot covering: harness version + path, "
            f"available verbs (ask modes / proxy state / 4 upstream "
            f"options / engine metadata / swarm sibling status), per-"
            f"engine key + protocol + UA-gating status, installed-snippet "
            f"freshness (warns if stale), wrapper-script + PATH status, "
            f"doctor summary, last 5 ask outputs with mode + verdict + "
            f"cost.  Use it instead of running 5+ individual queries to "
            f"discover the surface.\n\n"
            f"```bash\n"
            f"python -m harness introspect             # human-readable text\n"
            f"python -m harness introspect --format json  # structured (parse this)\n"
            f"python -m harness introspect --probe     # also live-probe engines (~$0.03: 3 keys × ~$0.01 each)\n"
            f"```\n\n"
            f"### Drill-down — `harness doctor`\n\n"
            f"`python -m harness doctor` runs a 7-check traffic-light "
            f"table.  Same data introspect surfaces in summary form; "
            f"use directly when you need the per-check fix-hints.  Note "
            f"the strategic plan's $195/mo budget covers MiMo + DeepSeek "
            f"+ Kimi (Qwen retired 2026-06-01).\n\n"
            f"### Support verbs\n\n"
            f"- `python -m harness doctor` — 7-check health table\n"
            f"- `python -m harness keys serve` — browser form for "
            f"per-provider API keys\n"
            f"- Per-provider Claude Code wrappers at "
            f"`{home_dir}\\.harness\\bin\\` (claude-mimo, claude-kimi, "
            f"claude-deepseek, etc.) for interactive sessions routed "
            f"to a specific provider.\n\n"
            f"**Operator manual**: `{repo_root}\\docs\\OPERATOR_GUIDE.md` (the consolidated operator/visual reference; absorbs the prior HARNESS_VISUAL_MANUAL.md per 2026-05-27 W14-DOCS-CONSOLIDATE).\n"
        )
    elif fmt == "prompt":
        return (
            f"You have xaxiu-harness installed at {repo_root}.  Three "
            f"things it provides:\n\n"
            f'1. **`python -m harness ask "..."`** — daily-driver LLM '
            f"verb.  Bare ask routes to ONE engine via the recommender "
            f"(~$0.01-0.05, ~30s).  `--audit` adds a second engine to "
            f"critique the answer for hallucinations (~$0.05).  "
            f"`--panel` fires 3 engines in parallel for high-stakes "
            f"design crossroads (~$0.20-0.30).  Outputs land at "
            f"`{repo_root}\\coord\\reviews\\ask-<ts>-<slug>\\` — read "
            f"`packet.md` (panel/audit modes) or the lone "
            f"`<engine>.md` (routed) for the answer.\n\n"
            f"2. **`python -m harness proxy start [--upstream <name>]`** "
            f"— OpenAI-compatible endpoint on 127.0.0.1:7879.  Four "
            f"upstreams: `kimi-http` (default), `deepseek-http` "
            f"(direct HTTP); `mimo-via-claude-code`, "
            f"`kimi-via-claude-code` (TOS-compliant Claude Code "
            f"subprocess for User-Agent-gated providers).  Run "
            f"`harness proxy upstreams` for the full list.  Set "
            f"`OPENAI_API_BASE=http://127.0.0.1:7879/v1` in the "
            f"consuming tool.\n\n"
            f"3. **xaxiu-swarm** (sibling repo) — agentic multi-file "
            f"dispatch via `xaxiu-swarm dispatch --backend <name> "
            f"--deliverable <path>`.  Use for multi-file refactors.\n\n"
            f"**Run `harness introspect --format json` FIRST** in a "
            f"fresh session — it returns one structured snapshot of "
            f"available verbs, per-engine key/health status, proxy "
            f"state, installed-snippet freshness, wrappers, doctor "
            f"summary, and recent ask outputs.  Single call, no "
            f"source-spelunking.  Use `harness doctor` for per-check "
            f"fix hints.\n\n"
            f"**Past asks**: `harness ask-history` lists past outputs; "
            f"`harness ask-show <id>` renders one; "
            f"`harness ask --rerun <dir>` re-asks the same question "
            f"(optionally with `--escalate audit` or `--escalate panel` "
            f"to upgrade the mode).\n\n"
            f"**Before making engine-specific claims, query first:** "
            f"`harness engines describe <name>` returns protocol "
            f"surfaces / UA gating / key prefixes / recommended task "
            f"classes / consumption surfaces in 1 call.  "
            f"`harness engines compatibility-matrix` shows the N×M "
            f"engine-vs-consumption-surface table.  "
            f"`harness engines recommend <class>` returns the empirical "
            f"routing pick.\n\n"
            f"When NOT to use `harness ask`: routine implementation "
            f"(do it yourself), factual lookups (WebSearch), multi-file "
            f"refactors (xaxiu-swarm), or third-party tool LLM calls "
            f"(use the proxy)."
        )
    elif fmt == "short":
        return (
            f"xaxiu-harness ({repo_root}).  Start with "
            f"`harness introspect --format json` — single-call snapshot "
            f"of verbs, engines, proxy state, doctor.  Then: "
            f'(1) `harness ask "..."` — daily LLM verb (routed '
            f"~$0.01-0.05, `--audit` ~$0.05, `--panel` ~$0.20-0.30, "
            f"`--rerun <dir>` to re-ask + `--escalate {{audit|panel}}` "
            f"to upgrade); (2) `harness proxy start [--upstream <name>]` "
            f"— OpenAI-compatible endpoint on 127.0.0.1:7879 with 5 "
            f"upstreams; (3) `xaxiu-swarm` sibling for agentic multi-"
            f"file dispatch.  `harness engines describe <name>` for "
            f"engine metadata.  `harness ask-history` + `ask-show` for "
            f"past outputs.  Reach for `--audit` when you've just made "
            f"a non-obvious factual claim worth sanity-checking."
        )
    else:
        raise ValueError(f"Unknown format: {fmt!r}")


@cli.command(name="agent-instructions")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(
        [
            "claude-md",
            "prompt",
            "short",
        ]
    ),
    default="claude-md",
    help=(
        "Output format.  'claude-md' = a CLAUDE.md section you can paste "
        "into ~/.claude/CLAUDE.md (works for all sessions on this machine). "
        "'prompt' = a one-shot prompt to paste into a new agent session. "
        "'short' = a one-paragraph hint."
    ),
)
def agent_instructions_cmd(fmt: str) -> None:
    """W14-AGENT-INSTRUCTIONS 2026-05-26: print a snippet that tells
    an agent (Claude Code, Cursor, etc.) the harness is available and
    how to use it.

    Use cases:

      \b
      harness agent-instructions > ~/.claude/CLAUDE.md.harness.md
        (then `cat` it into your user-level CLAUDE.md to have the
         harness auto-available in every Claude Code session on
         this machine)

      \b
      harness agent-instructions --format prompt | clip      (Windows)
      harness agent-instructions --format prompt | pbcopy    (macOS)
        (puts the prompt in your clipboard; paste into the next
         agent session manually)

      \b
      harness agent-instructions --format short
        (one-paragraph hint for embedding in a project's CLAUDE.md)
    """
    # Resolve the install path so the snippet has the right absolute
    # path baked in
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home()
    click.echo(_agent_instructions_snippet(fmt, repo_root, home_dir))
    sys.exit(0)




@cli.command(name="install-agent-instructions")
@click.option(
    "--target",
    "target_path",
    type=click.Path(
        dir_okay=False,
        path_type=Path,
    ),
    default=None,
    help=(
        "Path to the CLAUDE.md to append into.  Default: "
        "~/.claude/CLAUDE.md (Claude Code's user-level memory)."
    ),
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would be appended without writing."
)
@click.option(
    "--uninstall",
    is_flag=True,
    default=False,
    help="Remove the harness section from the target file "
    "(matched by W14-HARNESS-AGENT-INSTRUCTIONS marker).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-append even if the marker already exists (replaces the existing section).",
)
def install_agent_instructions_cmd(
    target_path: Path | None,
    dry_run: bool,
    uninstall: bool,
    force: bool,
) -> None:
    """W14-AGENT-INSTRUCTIONS 2026-05-26: append the harness snippet
    to ~/.claude/CLAUDE.md so EVERY Claude Code session on this
    machine knows the harness is available.

    Idempotent: re-running is a no-op unless --force is given.
    The appended section is wrapped in HTML comment markers
    (``<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->``) so it
    can be detected + removed cleanly.

    Examples:

      \b
      harness install-agent-instructions
        (appends to ~/.claude/CLAUDE.md, creating it if missing)

      \b
      harness install-agent-instructions --target ./CLAUDE.md
        (appends to the current project's CLAUDE.md instead)

      \b
      harness install-agent-instructions --dry-run
        (preview what would change)

      \b
      harness install-agent-instructions --uninstall
        (remove the harness section, leaving the rest of
         CLAUDE.md untouched)
    """
    # Resolve target
    if target_path is None:
        target_path = Path.home() / ".claude" / "CLAUDE.md"
    target_path = Path(target_path).resolve()

    # Markers for idempotent install / uninstall.  W14-AUTO-VERSION-STAMP
    # 2026-05-28: the START marker now embeds the version that wrote
    # the snippet, so `harness introspect` can warn "STALE" without
    # needing to hash the whole body.  Detection uses a prefix match
    # so old (un-versioned) installs still get detected + replaced.
    from harness import __version__ as _harness_version

    start_marker_prefix = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START"
    start_marker = f"<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START v{_harness_version} -->"
    end_marker = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->"

    # Build the snippet using the shared helper so this command can
    # never drift from `harness agent-instructions`.  Single source of
    # truth in `_agent_instructions_snippet` (W14-ASK-DOCS 2026-05-27).
    repo_root = Path(__file__).resolve().parents[2]
    home_dir = Path.home()
    snippet_body = _agent_instructions_snippet(
        "claude-md",
        repo_root,
        home_dir,
    )
    full_block = (
        f"\n{start_marker}\n"
        f"<!-- Auto-installed by `harness install-agent-instructions`. "
        f"Edit the harness repo, not this block. -->\n\n"
        f"{snippet_body}\n"
        f"{end_marker}\n"
    )

    # Read current state
    if target_path.exists():
        current = target_path.read_text(encoding="utf-8")
    else:
        current = ""

    # Locate existing block (prefix-tolerant for backward compat with
    # un-versioned installs from before 2026-05-28).
    has_block = start_marker_prefix in current and end_marker in current
    if has_block:
        prefix_idx = current.index(start_marker_prefix)
        # Find the closing `-->` of the START line so we know where
        # the (any-version) start marker ends + the body begins
        line_end = current.index("-->", prefix_idx) + len("-->")
        start_idx = prefix_idx
        end_idx = current.index(end_marker) + len(end_marker)
        # Track the existing version so we can report version delta
        existing_marker = current[prefix_idx:line_end]
        # Include the leading \n if present
        if start_idx > 0 and current[start_idx - 1] == "\n":
            start_idx -= 1
    else:
        existing_marker = ""

    # ---- Uninstall ----
    if uninstall:
        if not has_block:
            click.echo(f"  (no harness section found in {target_path})")
            sys.exit(0)
        new_content = current[:start_idx] + current[end_idx:]
        # Strip trailing newlines we just orphaned
        new_content = new_content.rstrip("\n") + "\n"
        if dry_run:
            click.echo(f"  Would remove the harness section from {target_path}")
            click.echo(f"  ({end_idx - start_idx} bytes)")
            sys.exit(0)
        target_path.write_text(new_content, encoding="utf-8")
        click.echo(
            click.style(
                f"  ✓ removed harness section from {target_path}",
                fg="green",
            )
        )
        sys.exit(0)

    # ---- Install / append ----
    if has_block and not force:
        click.echo(f"  Harness section already present in {target_path}.")
        click.echo("  Use --force to replace it, or --uninstall to remove.")
        sys.exit(0)

    if has_block and force:
        # Replace existing block
        new_content = current[:start_idx] + full_block + current[end_idx:]
        action = "replaced"
    else:
        # Append (with leading separator if file non-empty)
        if current and not current.endswith("\n"):
            current = current + "\n"
        new_content = current + full_block
        action = "appended to"

    if dry_run:
        click.echo(f"  Would {'replace' if action == 'replaced' else 'append'} in: {target_path}")
        click.echo()
        click.echo("  ---- preview ----")
        click.echo(full_block)
        click.echo("  ---- end preview ----")
        sys.exit(0)

    # Ensure parent dir exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(new_content, encoding="utf-8")
    # Surface the version transition when replacing (helps operators
    # confirm a `--force` actually refreshed the installed snippet)
    version_hint = ""
    if action == "replaced" and existing_marker:
        # Try to extract prior version from the existing START marker
        import re

        m = re.search(r"v([\d.]+)", existing_marker)
        prior_version = m.group(1) if m else "<unversioned>"
        if prior_version != _harness_version:
            version_hint = f"  (snippet version: v{prior_version} → v{_harness_version})"
        else:
            version_hint = f"  (snippet version: v{_harness_version}, unchanged)"
    elif action == "appended to":
        version_hint = f"  (snippet version: v{_harness_version})"
    click.echo(
        click.style(
            f"  ✓ harness section {action} {target_path}",
            fg="green",
        )
    )
    if version_hint:
        click.echo(click.style(version_hint, fg="white", dim=True))
    click.echo()
    click.echo(
        "  Every Claude Code session on this machine will now know "
        "the harness is available + how to use it."
    )
    sys.exit(0)




_VALID_TASK_CLASSES = (
    "default",
    "latency",
    "verbose",
    "cost",
    "high-volume",
    "multimodal",
    "audit",
)


@cli.command(name="ask")
@click.argument("question", required=False)
@click.option(
    "--file",
    "question_file",
    type=click.Path(
        exists=True,
        dir_okay=False,
        path_type=Path,
    ),
    default=None,
    help="Read the question from a file instead of an argument.",
)
@click.option(
    "--engines",
    default="",
    help=(
        "Comma-separated engine list.  Pinning overrides --task and --panel "
        "(used by scripts that need a specific engine, e.g. HANDOFF step 7)."
    ),
)
@click.option(
    "--task",
    "task_class",
    type=click.Choice(_VALID_TASK_CLASSES, case_sensitive=False),
    default="default",
    show_default=True,
    help=(
        "Routing task class for the bare (routed) default.  Picks one engine "
        "via `harness engines recommend <class>`.  Ignored if --engines or "
        "--panel is passed."
    ),
)
@click.option(
    "--panel",
    "panel_mode",
    is_flag=True,
    default=False,
    help=(
        "Fire the legacy 3-engine cross-engine panel "
        "(kimi-via-claude + mimo-via-claude + deepseek-via-claude) in parallel.  "
        "Was the bare default before v0.5.x; now opt-in.  Use for high-stakes "
        "design crossroads where vendor diversity matters."
    ),
)
@click.option(
    "--audit",
    "audit_mode",
    is_flag=True,
    default=False,
    help=(
        "Run producer → auditor flow.  The producer (routed default, or "
        "--engines / --task pick) answers; a DIFFERENT engine (picked via "
        "`recommend('audit', exclude={producer})`) then audits the answer "
        "and returns a structured VERDICT (PASS / PARTIAL / FAIL).  Useful "
        "for catching hallucinations and stress-testing factual claims.  "
        "~$0.05 / ~60s.  Conflicts with --panel."
    ),
)
@click.option(
    "--audit-engine",
    "audit_engine_override",
    default="",
    help=(
        "Override the auditor engine pick (default: chosen by recommender).  "
        "Implies --audit.  Conflicts with --auditors >1."
    ),
)
@click.option(
    "--auditors",
    "num_auditors",
    type=int,
    default=1,
    show_default=True,
    help=(
        "Number of auditors for --audit mode.  Default 1 (single auditor).  "
        "Pass `--auditors 2` for a 2-engine quorum (PASS/PARTIAL/FAIL "
        "computed by majority).  Capped at the number of distinct engines "
        "available after excluding the producer — currently 2 max with the "
        "Pattern B engine pool.  ~$0.10 for 2 auditors."
    ),
)
@click.option(
    "--research",
    "research_path",
    type=click.Path(
        exists=True,
        dir_okay=False,
        path_type=Path,
    ),
    default=None,
    help=(
        "Path to a markdown file of pre-fetched research context (e.g. "
        "WebSearch findings the calling agent gathered in its own session).  "
        "The content gets prepended to the question as RESEARCH CONTEXT and "
        "the routed engine synthesizes an answer using it.  Cheaper than "
        "asking Opus to both search AND synthesize — shift the synthesis "
        "to a routed Pattern B engine.  Saves a copy of the research to "
        "the output dir's research.md."
    ),
)
@click.option(
    "--rerun",
    "rerun_path",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
    default=None,
    help=(
        "Conversational re-ask: take the question from a previous ask-* "
        "dir and re-dispatch.  Optionally combine with --escalate "
        "{audit|panel} to upgrade the mode.  Saves to a new dir with "
        "parent_id field in summary.json for traceability.  Conflicts "
        "with positional QUESTION and --file."
    ),
)
@click.option(
    "--escalate",
    "escalate_mode",
    type=click.Choice(["audit", "panel"], case_sensitive=False),
    default=None,
    help=(
        "With --rerun, upgrade the dispatch mode of the re-ask.  "
        "`--escalate audit` adds a different-engine auditor to a routed "
        "or pinned producer.  `--escalate panel` switches to the 3-engine "
        "parallel fanout.  Without --rerun this flag is ignored."
    ),
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(
        file_okay=False,
        path_type=Path,
    ),
    default=None,
    help="Output directory for per-engine responses.  Default: "
    "coord/reviews/ask-<timestamp>-<slug>/",
)
@click.option(
    "--max-budget-usd", type=float, default=0.30, show_default=True, help="Per-engine spend cap."
)
@click.option(
    "--timeout-s", type=int, default=180, show_default=True, help="Per-engine timeout in seconds."
)
@click.option(
    "--no-save", is_flag=True, default=False, help="Skip saving to disk; print to stdout only."
)
@click.option(
    "--print-text",
    is_flag=True,
    default=False,
    help="Print full response text to stdout (default: table + path only).",
)
def ask_cmd(
    question: str | None,
    question_file: Path | None,
    engines: str,
    task_class: str,
    panel_mode: bool,
    audit_mode: bool,
    audit_engine_override: str,
    num_auditors: int,
    research_path: Path | None,
    rerun_path: Path | None,
    escalate_mode: str | None,
    output_dir: Path | None,
    max_budget_usd: float,
    timeout_s: int,
    no_save: bool,
    print_text: bool,
) -> None:
    """W14-HARNESS-ASK 2026-05-26 / W14-ASK-ROUTED + ASK-AUDIT 2026-05-27
    / W14-ASK-RERUN 2026-05-28: daily-driver cross-engine LLM call.

    THREE modes + conversational re-ask:

    \b
      routed (default)   1 engine via routing recommender,   ~$0.01-0.05
      --audit            producer → auditor (2 engines),     ~$0.05
      --panel            3-engine parallel fanout,           ~$0.20-0.30
      --engines X,Y,Z    pin specific engine(s), bypass recommender
      --rerun <dir>      re-ask the question from a prior ask-* dir
                         (optionally with --escalate {audit|panel})

    Examples:

      \b
      harness ask "should we deprecate the legacy swarm/kimi-api?"
      harness ask "..." --task latency               # → deepseek-via-claude
      harness ask "..." --audit                      # fact-check own claims
      harness ask "..." --panel                      # 3-engine fanout
      harness ask "..." --engines mimo-via-claude    # pin explicit
      harness ask --file question.md
      harness ask --rerun coord/reviews/ask-...      # repeat the question
      harness ask --rerun coord/reviews/ask-... --escalate audit
                                                     # add audit layer
      harness ask --rerun coord/reviews/ask-... --escalate panel
                                                     # promote to 3-engine

    NOTE: bare `harness ask` was a 3-engine panel before v0.5.x.
    Pass `--panel` to keep that behavior.  The routed default uses
    `harness engines recommend <task-class>` to pick one engine.

    Cross-engine PANEL output: question.md + <engine>.md per engine
    + packet.md (synthesis-ready) + summary.json.
    Routed output: question.md + <engine>.md + summary.json
    (no packet.md — the lone engine file IS the synthesis-ready artifact).
    Audit output: question.md + producer-<engine>.md + audit-<engine>.md
    + packet.md + summary.json (with `verdict` field: PASS / PARTIAL / FAIL).
    Rerun output: same as the mode resolved by --escalate; summary.json
    carries `parent_id` for traceability.
    """
    import datetime
    from harness.ask import (
        DEFAULT_ENGINES,
        _slugify,
        run_panel,
        run_audit,
        save_panel,
    )

    # --escalate is meaningless without --rerun
    if escalate_mode and rerun_path is None:
        click.echo(
            click.style(
                "WARNING: --escalate has no effect without --rerun (ignored).",
                fg="yellow",
            ),
            err=True,
        )
        escalate_mode = None

    # Phase 2.2: --rerun loads question + engine defaults from a prior
    # ask dir.  --escalate {audit|panel} optionally upgrades the mode.
    parent_summary: dict = {}
    parent_id: str = ""
    if rerun_path is not None:
        if question or question_file:
            click.echo(
                click.style(
                    "ERROR: --rerun is incompatible with positional "
                    "QUESTION and --file (the question comes from the "
                    "rerun directory).",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)

        q_file = rerun_path / "question.md"
        if not q_file.exists():
            click.echo(
                click.style(
                    f"ERROR: {rerun_path} does not contain question.md "
                    f"— not a valid ask-* directory.",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)

        # Parse the question.md format ("# Panel question\n\n<text>\n")
        q_raw = q_file.read_text(encoding="utf-8").strip()
        if q_raw.startswith("# Panel question") and "\n\n" in q_raw:
            q_raw = q_raw.split("\n\n", 1)[1]
        # Synthesize the positional question for the resolver below
        question = q_raw.strip()
        parent_id = rerun_path.name

        # Load parent summary to learn original mode + engines
        summary_file = rerun_path / "summary.json"
        if summary_file.exists():
            try:
                parent_summary = json.loads(
                    summary_file.read_text(encoding="utf-8"),
                )
            except (json.JSONDecodeError, OSError):
                parent_summary = {}

        parent_mode = parent_summary.get("mode", "routed")
        # Producer engine(s) = anything that wasn't the auditor
        parent_engines = [
            r.get("engine")
            for r in parent_summary.get("results", [])
            if r.get("engine") and r.get("role") != "audit"
        ]

        # Apply --escalate (or inherit parent's mode)
        normalized_escalate = (escalate_mode or "").lower()
        if normalized_escalate == "audit":
            audit_mode = True
            # Audit needs exactly 1 producer.  Use parent's first engine
            # that wasn't the auditor.  If parent was panel, this picks
            # the first of the 3.
            if parent_engines:
                engines = parent_engines[0]
        elif normalized_escalate == "panel":
            panel_mode = True
            # Leave engines empty so panel_mode picks DEFAULT_ENGINES
            engines = ""
        else:
            # No escalation — inherit parent's mode + engine set
            if parent_mode == "panel":
                panel_mode = True
            elif parent_mode == "audit":
                audit_mode = True
                if parent_engines:
                    engines = parent_engines[0]
            elif parent_engines:
                # Original was routed or pinned — pin those engines
                engines = ",".join(e for e in parent_engines if e)

    # --audit-engine implies --audit.  Cheaper UX than requiring both.
    if audit_engine_override:
        audit_mode = True

    # --auditors > 1 implies --audit and conflicts with --audit-engine
    if num_auditors > 1:
        audit_mode = True
        if audit_engine_override:
            click.echo(
                click.style(
                    "ERROR: --audit-engine pins a single engine; "
                    "--auditors >1 requests a quorum.  These conflict.  "
                    "Pick one.",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)

    # Conflict checks (mutually exclusive flag combinations)
    if audit_mode and panel_mode:
        click.echo(
            click.style(
                "ERROR: --audit and --panel are mutually exclusive.  "
                "--audit runs a producer→auditor flow (2 engines, "
                "sequential); --panel fires 3 engines in parallel.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(2)

    # Resolve question source
    if question_file is not None:
        question_text = question_file.read_text(encoding="utf-8").strip()
    elif question:
        question_text = question.strip()
    else:
        click.echo(
            click.style(
                "ERROR: provide a question argument or --file path",
                fg="red",
            ),
            err=True,
        )
        sys.exit(2)

    if not question_text:
        click.echo(
            click.style("ERROR: question is empty", fg="red"),
            err=True,
        )
        sys.exit(2)

    # W14-ASK-RESEARCH 2026-05-28 (Phase 4.2): prepend pre-fetched
    # research context to the question.  Useful when the calling agent
    # (typically Opus) did WebSearch itself and wants to shift the
    # synthesis to a cheaper routed engine.
    research_content = ""
    if research_path is not None:
        try:
            research_content = research_path.read_text(
                encoding="utf-8",
            ).strip()
        except OSError as e:
            click.echo(
                click.style(
                    f"ERROR: could not read --research file {research_path}: {e}",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)
        if research_content:
            # Wrap with explicit framing so the engine knows it's
            # context-not-content
            question_text = (
                "You have been given pre-fetched research context "
                "below.  Use it (and your prior knowledge) to answer "
                "the QUESTION at the end.  Cite specific lines or "
                "sources from the research when they bear directly "
                "on your answer.  Do not invent sources.\n\n"
                "RESEARCH CONTEXT:\n"
                f"{research_content}\n\n"
                "QUESTION:\n"
                f"{question_text}"
            )

    # Resolve engines + mode.  Precedence is --engines > --audit > --panel
    # > --task (the routed default).
    #
    # Mode semantics:
    #   routed  → recommender-picked single engine; question.md +
    #             <engine>.md + summary.json (no packet.md).
    #   audit   → producer + auditor (2 engines, sequential);
    #             question.md + producer-<engine>.md + audit-<engine>.md
    #             + packet.md + summary.json (verdict field).
    #   panel   → user-pinned engines (via --engines) OR --panel mode;
    #             question.md + <engine>.md per engine + packet.md +
    #             summary.json.  Pin path stays panel-shape even for
    #             1 engine, so HANDOFF.md step 7 + scripted callers see
    #             no output-shape drift.
    engine_list: tuple[str, ...]
    mode: str
    rationale: str = ""
    if engines:
        engine_list = tuple(e.strip() for e in engines.split(",") if e.strip())
        if audit_mode and len(engine_list) != 1:
            click.echo(
                click.style(
                    f"ERROR: --audit requires exactly 1 producer engine; "
                    f"got {len(engine_list)} via --engines "
                    f"({','.join(engine_list)}).  Either drop --audit or "
                    f"pin a single engine.",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)
        # Explicit pin = panel-shape output regardless of engine count.
        # Preserves backward compat with the pre-v0.5.x pin behavior.
        # (--audit overrides this below.)
        mode = "panel"
    elif panel_mode:
        engine_list = DEFAULT_ENGINES
        mode = "panel"
    else:
        # Routed default — use the health-aware empirical recommender.
        # W14-DISPATCH-HEALTH-AWARE-FALLBACK 2026-05-28: falls through
        # to alternates when the primary pick is recently terminated.
        from harness.engines.routing_recommend import recommend_healthy

        rec = recommend_healthy(task_class)
        if rec is None:
            click.echo(
                click.style(
                    f"ERROR: no healthy engine available for task class "
                    f"{task_class!r}.  All candidates are recently "
                    f"terminated.  Check `harness engines health` + "
                    f"`harness keys list` to diagnose.",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(1)
        engine_list = (rec.engine,)
        mode = "routed"
        rationale = rec.rationale

    # --audit overrides whatever mode the engine resolution set.
    if audit_mode:
        mode = "audit"

    # Resolve output dir
    if output_dir is None and not no_save:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = _slugify(question_text)
        repo_root = Path(__file__).resolve().parents[2]
        output_dir = repo_root / "coord" / "reviews" / f"ask-{ts}-{slug}"

    # Mode-specific dispatch banner
    producer_engine_for_audit: str = engine_list[0] if audit_mode else ""
    if mode == "audit":
        # Resolved producer is known; auditor is picked inside run_audit.
        click.echo(
            f"[ask] audit: producer = {producer_engine_for_audit}  "
            f"(budget ${max_budget_usd:.2f}, timeout {timeout_s}s)"
        )
        if audit_engine_override:
            click.echo(f"      auditor: {audit_engine_override} (forced via --audit-engine)")
    elif mode == "routed":
        click.echo(
            f"[ask] routed (task={task_class}) → {engine_list[0]}  "
            f"(budget ${max_budget_usd:.2f}, timeout {timeout_s}s)"
        )
        if rationale:
            short = rationale.replace("\n", " ").strip()
            if len(short) > 110:
                short = short[:107] + "..."
            click.echo(f"      {short}")
    elif engines:
        # --engines pinning (single or multiple)
        click.echo(
            f"[ask] pinned: firing {len(engine_list)} engine(s) "
            f"({','.join(engine_list)})  "
            f"(budget ${max_budget_usd:.2f} each, timeout {timeout_s}s)..."
        )
    else:
        # --panel
        click.echo(
            f"[ask] panel: firing {len(engine_list)} engines in parallel  "
            f"(budget ${max_budget_usd:.2f} each, timeout {timeout_s}s)..."
        )
    if output_dir is not None and not no_save:
        click.echo(f"      output: {output_dir}")

    # Dispatch.  Audit uses sequential producer→auditor; routed + panel
    # use parallel fanout (1 or N engines).
    roles: list[str] = []
    extra_summary: dict = {}
    # If this is a --rerun, carry the parent id forward so the new
    # summary.json is self-describing.  Both branches below `.update()`
    # rather than reassign so this survives.
    if parent_id:
        extra_summary["parent_id"] = parent_id
        if parent_summary.get("mode"):
            extra_summary["parent_mode"] = parent_summary["mode"]
        if escalate_mode:
            extra_summary["escalated_from"] = parent_summary.get("mode", "?")
            extra_summary["escalated_to"] = (
                "audit" if audit_mode else "panel" if panel_mode else mode
            )

    # W14-ASK-RESEARCH 2026-05-28: surface research metadata
    if research_content:
        extra_summary["research_findings_chars"] = len(research_content)
        extra_summary["research_findings_source"] = (
            str(research_path) if research_path else "inline"
        )
    if mode == "audit":
        outcome = run_audit(
            question_text,
            producer_engine=producer_engine_for_audit,
            max_budget_usd=max_budget_usd,
            timeout_s=timeout_s,
            audit_engine_override=audit_engine_override,
            num_auditors=num_auditors,
        )
        if not outcome.auditors:
            # Producer failed (or auditor selection failed); the audit
            # step was skipped.  Single result, no verdict.
            results = [outcome.producer]
            roles = ["producer"]
            extra_summary.update(
                {
                    "producer_engine": producer_engine_for_audit,
                    "auditor_engine": "",
                    "auditor_engines": [],
                    "num_auditors_requested": num_auditors,
                    "verdict": None,
                    "audit_skipped_reason": (
                        "producer dispatch failed"
                        if not outcome.producer.ok
                        else "no audit engines available"
                    ),
                }
            )
        else:
            results = [outcome.producer, *outcome.auditors]
            # Multi-auditor: roles are producer + audit-1 + audit-2 ...
            # For single-auditor (back-compat), keep the unsuffixed role.
            if len(outcome.auditors) == 1:
                roles = ["producer", "audit"]
            else:
                roles = ["producer"] + [f"audit-{i + 1}" for i in range(len(outcome.auditors))]
            extra_summary.update(
                {
                    "producer_engine": producer_engine_for_audit,
                    "auditor_engine": outcome.auditor_engine,  # back-compat: first
                    "auditor_engines": list(outcome.auditor_engines),
                    "num_auditors_requested": num_auditors,
                    "num_auditors_actual": len(outcome.auditors),
                    "verdict": outcome.verdict,
                    # Per-auditor breakdown is only useful for N > 1
                    **({"verdicts": outcome.verdicts} if len(outcome.auditors) > 1 else {}),
                }
            )
    else:
        results = run_panel(
            question_text,
            engines=engine_list,
            max_budget_usd=max_budget_usd,
            timeout_s=timeout_s,
        )

    # Print summary table (always)
    click.echo()
    click.echo(
        f"{'engine':<24} {'OK':<4} {'elapsed':<10} {'in':<6} {'out':<6} {'cost':<10} {'alias':<6}"
    )
    click.echo("-" * 75)
    total_cost = 0.0
    for i, r in enumerate(results):
        if r.ok:
            ok_styled = click.style("OK", fg="green")
        else:
            ok_styled = click.style("FAIL", fg="red")
        # Audit mode: prefix engine name with role for clarity in the table
        if mode == "audit" and i < len(roles) and roles[i]:
            label = f"{roles[i]}:{r.engine}"
        else:
            label = r.engine
        click.echo(
            f"  {label:<22} {ok_styled:<11} "
            f"{r.elapsed_s:>5.1f}s   "
            f"{r.tokens_in:<6} {r.tokens_out:<6} "
            f"${r.cost_usd:<8.4f} {r.winning_alias or '—':<6}"
        )
        total_cost += r.cost_usd
    click.echo()
    click.echo(f"  total cost: ${total_cost:.4f}")

    # Audit verdict line (always shown when an audit verdict is present)
    if mode == "audit" and extra_summary.get("verdict"):
        v = extra_summary["verdict"]
        verdict_str = v.get("verdict", "UNKNOWN")
        verdict_color = {
            "PASS": "green",
            "PARTIAL": "yellow",
            "FAIL": "red",
            "UNKNOWN": "magenta",
        }.get(verdict_str, "magenta")
        click.echo()
        click.echo(click.style(f"  VERDICT: {verdict_str}", fg=verdict_color, bold=True))
        summary_line = v.get("summary", "").strip().splitlines()[0:1]
        if summary_line:
            click.echo(f"    {summary_line[0]}")

    if not no_save and output_dir is not None:
        save_panel(
            question_text,
            results,
            output_dir,
            mode=mode,
            extra_summary=extra_summary if extra_summary else None,
            roles=roles if roles else None,
        )
        # Persist research context alongside outputs so the ask is
        # self-describing (the synthesis quality depends on the input
        # the engine saw).
        if research_content:
            (output_dir / "research.md").write_text(
                research_content,
                encoding="utf-8",
            )
        if mode == "routed":
            click.echo(f"  saved {len(results)} response file + summary.json")
        else:
            click.echo(f"  saved {len(results)} response files + packet.md + summary.json")
        click.echo()
        click.echo(
            click.style(
                f"  → review at {output_dir}",
                fg="cyan",
            )
        )

    if print_text:
        click.echo()
        click.echo("=" * 75)
        for i, r in enumerate(results):
            click.echo()
            role = roles[i] if (roles and i < len(roles)) else ""
            label = f"{role}: {r.engine}" if role else r.engine
            # W14-ASK-NOISE (reviewer gap #3): flag a syntactically-OK but
            # garbage response so it doesn't silently corrupt the compare.
            noise = getattr(r, "noise", "") if r.ok else ""
            if noise:
                label += f"  ⚠ {noise}"
            click.echo(click.style(f"### {label}", fg="yellow", bold=True))
            click.echo()
            if noise:
                click.echo(
                    click.style(
                        f"⚠ possible low-quality response ({noise}): this engine "
                        f"may have returned an empty body or leaked tool-call "
                        f"markup — weight it accordingly in the comparison below.",
                        fg="red",
                    )
                )
                click.echo()
            click.echo(r.text if r.ok else f"FAILED: {r.error}")

    failed = [r for r in results if not r.ok]
    sys.exit(1 if failed else 0)












# ---------------------------------------------------------------------------
# Canonical STATUS.csv tracker (roster #19)
# ---------------------------------------------------------------------------




_STATUS_HEADER = ["ID", "Category", "Title", "Status", "Owner", "Effort", "Updated", "Notes"]






















@cli.command()
@click.option("--show-set", is_flag=True, help="Show which API keys are set.")
def env(show_set: bool) -> None:
    """Check which API keys are set (reports per-key + per-alias, never values).

    Patch 2026-05-21: extended to surface the v2 proxy's per-key indexed
    aliases (KIMI_API_KEY_1..4 → k1..k4) so the operator can see the real
    state of the 4-key pool. The legacy singular ``KIMI_API_KEY`` is still
    reported (and serves as a fallback for k1 per ``resolve_keys``).
    """
    from harness.secrets.dpapi import has_secret

    # Legacy single-key surface (used by v1 dispatchers + as k1 fallback)
    legacy_keys = ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    for key_name in legacy_keys:
        if os.environ.get(key_name) or has_secret(key_name):
            click.echo(f"{key_name}: SET")
        else:
            click.echo(f"{key_name}: MISSING")

    # v2 proxy per-alias pool (KIMI_API_KEY_1..4 → k1..k4)
    click.echo("")
    click.echo("v2 proxy pool (Kimi-API per-alias):")
    try:
        from harness.proxy.app import resolve_keys

        resolved = resolve_keys()
    except Exception as exc:
        resolved = {}
        click.echo(f"  (resolve_keys failed: {exc})")
    for n in range(1, 5):
        alias = f"k{n}"
        env_var = f"KIMI_API_KEY_{n}"
        env_present = bool(os.environ.get(env_var))
        dpapi_present = has_secret(env_var)
        if alias in resolved:
            source = "env" if env_present else ("DPAPI" if dpapi_present else "legacy")
            click.echo(f"  {alias} ({env_var}): SET (source={source})")
        else:
            click.echo(f"  {alias} ({env_var}): MISSING")
    click.echo(
        f"v2 pool size: {len(resolved)}/4 (6 slots/key -> {len(resolved) * 6}/24 concurrent capacity)"
    )
    sys.exit(0)


_ENV_WIZARD_KEYS: list[tuple[str, str]] = [
    # (env_var_name, plain-language purpose)
    ("KIMI_API_KEY", "Kimi (Moonshot) — primary agentic engine"),
    ("DEEPSEEK_API_KEY", "DeepSeek — V-file-spanning + math-heavy work"),
    ("MIMO_API_KEY", "MiMo — audit + brainstorm panels"),
    ("ANTHROPIC_API_KEY", "Anthropic — Claude API fallback (optional)"),
    ("GEMINI_API_KEY", "Gemini — secondary engine (optional)"),
]


@cli.command(name="env-wizard")
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Re-prompt for keys that are already set (default: "
    "skip set keys and only prompt for missing ones).",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    default=False,
    help="Print the wizard plan without prompting; used by tests and dry-run.",
)
def env_wizard_cmd(overwrite: bool, non_interactive: bool) -> None:
    """W10-ENV-VAR-WIZARD: guided API-key population.

    Walks through each required API key, prompts the operator to
    paste a value (or skip), and stores it in DPAPI via
    ``harness.secrets.dpapi.encrypt_secret``.  After each entry,
    runs a presence probe to confirm.

    Idempotent: re-running shows current state.  Pass ``--overwrite``
    to re-prompt for keys that are already set.

    Operator-friendly: no Python knowledge required.  The wizard
    explains each key in plain language (what it's for, whether
    it's required).  Operators can paste keys; values are hidden
    in the prompt and never echoed back.

    Per [[user_non_technical_role]] memory: the operator can run
    CLI commands + paste values but cannot read tracebacks.  The
    wizard surfaces errors with one-line "what to do" messages.
    """
    from harness.secrets.dpapi import has_secret, encrypt_secret

    click.echo("=" * 60)
    click.echo("  harness env-wizard — API key setup")
    click.echo("=" * 60)
    click.echo(
        "\nFor each engine, you'll see whether a key is already set.\n"
        "If MISSING, paste your key (or press Enter to skip).\n"
        "Keys are stored securely via Windows DPAPI — only your\n"
        "Windows user can decrypt them.\n"
    )

    set_count = 0
    new_count = 0
    skip_count = 0

    for key_name, purpose in _ENV_WIZARD_KEYS:
        env_present = bool(os.environ.get(key_name))
        dpapi_present = has_secret(key_name)
        present = env_present or dpapi_present
        status = "SET" if present else "MISSING"
        source = ""
        if env_present and dpapi_present:
            source = "  (env + DPAPI)"
        elif env_present:
            source = "  (env)"
        elif dpapi_present:
            source = "  (DPAPI)"

        click.echo(f"\n[{status}] {key_name}{source}")
        click.echo(f"        {purpose}")

        if present and not overwrite:
            click.echo("        -> already set, skipping (pass --overwrite to re-prompt)")
            set_count += 1
            continue

        if non_interactive:
            click.echo("        -> would prompt (non-interactive mode; skipping)")
            skip_count += 1
            continue

        # Prompt for value (hide input so the key isn't echoed)
        value = click.prompt(
            f"        Paste {key_name} (or empty to skip)",
            hide_input=True,
            default="",
            show_default=False,
        )
        value = value.strip()
        if not value:
            click.echo("        -> skipped (empty input)")
            skip_count += 1
            continue

        try:
            encrypt_secret(key_name, value)
        except Exception as exc:
            click.echo(f"        [X] failed to store key: {exc}", err=True)
            click.echo("        -> retry the wizard once you've resolved the DPAPI issue", err=True)
            sys.exit(4)

        # Confirm
        if has_secret(key_name):
            click.echo(f"        [OK] {key_name} stored in DPAPI")
            new_count += 1
        else:
            click.echo(
                f"        [X] {key_name} write reported ok but presence probe failed", err=True
            )
            sys.exit(4)

    click.echo("\n" + "=" * 60)
    click.echo(
        f"  Wizard complete: {set_count} already-set, "
        f"{new_count} newly stored, {skip_count} skipped"
    )
    click.echo("=" * 60)
    click.echo("\nVerify with: `harness env`")
    sys.exit(0)
















# W14-KEY-ROTATION-PLAYBOOK 2026-05-28: provider → env-var lookup for
# the env-rotate verb.  The full pattern of "what env var does this
# engine use" lives in harness._constants.API_KEY_ENV_VARS but that's
# keyed by engine name (lower-case); the operator-facing rotate verb
# accepts a friendlier short name.
_ROTATE_ENGINE_TO_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "KIMI_API_KEY",
    "mimo": "MIMO_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
}


@cli.command(name="env-rotate")
@click.argument("engine", required=True)
@click.option(
    "--no-keep-previous",
    is_flag=True,
    default=False,
    help="Don't preserve the old key as a *_PREVIOUS_<ts> backup.  "
    "Use for known-compromised keys you want gone immediately.  "
    "Default: keep for 24h emergency rollback.",
)
@click.option(
    "--from-stdin",
    is_flag=True,
    default=False,
    help="Read the new key from stdin instead of prompting (for scripted rotation).",
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would happen without touching DPAPI."
)
def env_rotate_cmd(engine: str, no_keep_previous: bool, from_stdin: bool, dry_run: bool) -> None:
    """W14-KEY-ROTATION-PLAYBOOK: rotate the API key for ENGINE.

    Reads the new key from a hidden prompt (or stdin with --from-stdin),
    atomically replaces the DPAPI-stored secret, and preserves the
    previous value as ``<NAME>_PREVIOUS_<timestamp>`` for 24h emergency
    rollback unless ``--no-keep-previous``.

    ENGINE is the short engine name (deepseek, kimi, mimo, anthropic,
    gemini, qwen).  The verb maps it to the canonical env-var name
    and rotates the matching DPAPI secret.

    The audit ledger gets a ``key_rotation`` event (no key value) via
    the W14-AUDIT-CHAIN-HMAC tamper-evident chain.

    See ``docs/KEY_ROTATION_PLAYBOOK.md`` for the full operator workflow
    (when to rotate, smoke-test after, rollback procedure).

    Exit codes:
        0 — rotation succeeded
        1 — engine name unknown
        2 — empty key / user cancelled
        3 — DPAPI unavailable (non-Windows host) — use env var directly
    """
    eng_lower = engine.lower().strip()
    if eng_lower not in _ROTATE_ENGINE_TO_ENV:
        click.echo(
            f"Unknown engine: {engine!r}.  Supported: {', '.join(sorted(_ROTATE_ENGINE_TO_ENV))}",
            err=True,
        )
        raise SystemExit(1)
    env_name = _ROTATE_ENGINE_TO_ENV[eng_lower]

    if dry_run:
        click.echo(f"[dry-run] Would rotate {env_name} via DPAPI.")
        click.echo(f"[dry-run] keep_previous={not no_keep_previous}")
        click.echo("[dry-run] No prompt for key; no DPAPI write.")
        return

    # Read the new key.
    if from_stdin:
        new_value = sys.stdin.read().rstrip("\n").rstrip("\r")
    else:
        new_value = click.prompt(
            f"Paste new {env_name}",
            hide_input=True,
            confirmation_prompt=False,
        )
    new_value = new_value.strip()
    if not new_value:
        click.echo("Empty key — rotation cancelled.", err=True)
        raise SystemExit(2)

    try:
        from harness.secrets.dpapi import rotate_secret
        from harness.audit_jsonl import append_key_rotation_event
    except (ImportError, NotImplementedError) as exc:
        click.echo(
            f"Key rotation requires Windows DPAPI ({exc}).\n"
            f"On Linux/macOS, set the env var directly:\n"
            f"  export {env_name}=<new-value>",
            err=True,
        )
        raise SystemExit(3)

    try:
        result = rotate_secret(
            env_name,
            new_value,
            keep_previous=not no_keep_previous,
        )
    except NotImplementedError as exc:
        click.echo(
            f"Key rotation requires Windows DPAPI ({exc}).\n"
            f"On Linux/macOS, set the env var directly:\n"
            f"  export {env_name}=<new-value>",
            err=True,
        )
        raise SystemExit(3)
    except Exception as exc:
        click.echo(f"Rotation failed: {exc}", err=True)
        raise SystemExit(2)

    # Log the rotation (no key value) into the chained audit ledger.
    append_key_rotation_event(
        provider=eng_lower,
        previous_kept_as=result.get("previous_kept_as"),
        had_previous_value=bool(result.get("had_previous_value")),
    )

    click.echo(f"Rotated {env_name}.")
    prev = result.get("previous_kept_as")
    if prev:
        click.echo(f"  previous kept as: {prev} (delete after smoke test)")
    elif result.get("had_previous_value"):
        click.echo("  previous value: DISCARDED (--no-keep-previous)")
    else:
        click.echo("  (first-time write — no previous value existed)")

    click.echo(
        "\nNext steps:\n"
        f'  1. Smoke-test: harness ask --engines {eng_lower} "Reply OK."\n'
        f"  2. If working, delete the backup: "
        f'`python -c "from harness.secrets.dpapi import delete_secret; '
        f"delete_secret('{prev}')\"`\n"
        if prev
        else f'\nNext: smoke-test with `harness ask --engines {eng_lower} "Reply OK."`'
    )




















@cli.command(name="ask-history")
@click.option(
    "--last",
    "last_n",
    type=int,
    default=20,
    show_default=True,
    help="Cap the result count.  Pass 0 for unlimited.",
)
@click.option(
    "--mode",
    "mode_filter",
    type=click.Choice(["routed", "audit", "panel"]),
    default=None,
    help="Filter to one mode.  Default: all modes.",
)
@click.option(
    "--verdict",
    "verdict_filter",
    type=click.Choice(
        ["PASS", "PARTIAL", "FAIL", "UNKNOWN"],
        case_sensitive=False,
    ),
    default=None,
    help="Filter by audit verdict.  Implies --mode audit.",
)
@click.option(
    "--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True
)
def ask_history_cmd(
    last_n: int,
    mode_filter: str | None,
    verdict_filter: str | None,
    fmt: str,
) -> None:
    """W14-ASK-HISTORY 2026-05-28 (Phase 2.3): list past `harness ask`
    outputs from `coord/reviews/`.

    Pairs with `harness ask --rerun <dir>` (Phase 2.2): use this to
    find an id, then re-ask with that id.

    Examples:

      \b
      harness ask-history --last 10                # last 10 asks
      harness ask-history --mode audit             # audit-mode only
      harness ask-history --verdict FAIL           # past failures
      harness ask-history --format json | jq '.'   # programmatic
    """
    from harness.ask_history import list_asks, render_history_text

    rows = list_asks(
        last_n=last_n if last_n > 0 else 0,
        mode_filter=mode_filter,
        verdict_filter=verdict_filter,
    )
    if fmt == "json":
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        click.echo(render_history_text(rows))
    sys.exit(0)


@cli.command(name="ask-show")
@click.argument("ask_id")
@click.option(
    "--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True
)
def ask_show_cmd(ask_id: str, fmt: str) -> None:
    """W14-ASK-HISTORY 2026-05-28 (Phase 2.3): render one past ask
    output: question, mode, engines, verdict (if audit), per-engine
    responses.

    Pass the directory name from `harness ask-history` output, e.g.
    `harness ask-show ask-20260528-115620-some-question-slug`.
    """
    from harness.ask_history import load_ask, render_ask_text

    data = load_ask(ask_id)
    if "error" in data:
        click.echo(click.style(f"ERROR: {data['error']}", fg="red"), err=True)
        sys.exit(1)
    if fmt == "json":
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_ask_text(data))
    sys.exit(0)


@cli.command(name="introspect")
@click.option(
    "--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True
)
@click.option(
    "--probe",
    "with_probe",
    is_flag=True,
    default=False,
    help="Run live engine probes (real network round-trips, "
    "costs a few cents).  Off by default — snapshot is "
    "read-only and cheap.",
)
def introspect_cmd(fmt: str, with_probe: bool) -> None:
    """W14-INTROSPECT 2026-05-28 (Phase 2.1): single-call capability +
    state snapshot.

    The verb a fresh Claude Code session should run FIRST to learn
    what's available + working without spelunking source.

    Output covers: harness version + path, available verbs (ask modes /
    proxy state + 5 upstreams / engine metadata / xaxiu-swarm sibling
    status), per-engine key + protocol + UA-gating summary, installed-
    snippet freshness check, wrapper-script + PATH status, doctor
    summary, last 5 ask outputs with mode + verdict + cost.

    Default (`--format text`) is human-readable; `--format json` is
    the recommended programmatic surface for agents.

    Run with `--probe` for live engine round-trips (catches 401s the
    presence check cannot).  Costs a few cents per run.
    """
    from harness.introspect import build_snapshot, render_text

    snapshot = build_snapshot(probe=with_probe)
    if fmt == "json":
        click.echo(json.dumps(snapshot, indent=2, default=str))
    else:
        click.echo(render_text(snapshot))
    sys.exit(0)


@cli.command(name="doctor")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
@click.option(
    "--probe",
    "with_probe",
    is_flag=True,
    default=False,
    help="Also run a LIVE network probe against each configured "
    "engine (real ~5-token round-trips).  Catches expired / "
    "typo'd / quota-exhausted keys that the presence check "
    "cannot.  Costs a few cents per run, takes several "
    "seconds per engine.  P2 audit fix 2026-05-27.",
)
def doctor_cmd(fmt: str, with_probe: bool) -> None:
    """Preflight: check git, python, DPAPI, engine keys, coord/ perms, Task Scheduler.

    By default this only checks key PRESENCE.  Use ``--probe`` to also
    do a live network round-trip per engine (catches dead / expired /
    typo'd keys that simple presence checks cannot).
    """
    import dataclasses
    from harness.doctor import run_all, overall_severity

    diagnoses = run_all(with_probe=with_probe)
    overall = overall_severity(diagnoses)

    if fmt == "json":
        click.echo(
            json.dumps(
                {
                    "overall": overall,
                    "checks": [dataclasses.asdict(d) for d in diagnoses],
                },
                indent=2,
            )
        )
    else:
        glyph = {"ok": "[OK]", "warn": "[!]", "fail": "[X]"}
        click.echo("harness doctor — preflight diagnostics")
        click.echo("=" * 50)
        for d in diagnoses:
            click.echo(f"  {glyph.get(d.severity, '?')} {d.name:<16} {d.message}")
            if d.fix:
                click.echo(f"          fix: {d.fix}")
        click.echo("=" * 50)
        click.echo(f"overall: {overall.upper()}")

    sys.exit(0 if overall != "fail" else 1)






@cli.group(name="keys")
def keys_group() -> None:
    """W14-HARNESS-KEYS-WEB-UI: interactive API-key entry + listing.

    Subcommands:
      serve  - launch a local HTTP form for entering provider API keys
               (binds 127.0.0.1, ephemeral port, token-gated)
      list   - print the current key-status table without launching UI
    """


@keys_group.command(name="serve")
@click.option(
    "--port", type=int, default=0, help="Bind to this port (default: OS-assigned ephemeral)."
)
@click.option("--no-open", is_flag=True, help="Don't auto-open the browser; just print the URL.")
@click.option(
    "--idle-timeout",
    type=int,
    default=600,
    help="Self-shutdown after this many idle seconds (default 600).",
)
def keys_serve(port: int, no_open: bool, idle_timeout: int) -> None:
    """W14-HARNESS-KEYS-WEB-UI: launch the interactive key-entry form.

    Binds to 127.0.0.1 (loopback) only.  Token-gated.  Form lets the
    operator paste each provider key, live-probe via /api/test, and
    save to .env in the current working directory.  Self-shuts-down
    after the idle-timeout.
    """
    from harness.keys_ui import serve_key_ui

    serve_key_ui(
        port=port,
        auto_open=not no_open,
        idle_timeout_seconds=float(idle_timeout),
    )


@keys_group.command(name="list")
@click.option("--format", "fmt", type=click.Choice(["pretty", "json"]), default="pretty")
def keys_list(fmt: str) -> None:
    """Show the current API-key status (no UI, no probe).

    For each known provider: env-var name, source (shell env / .env /
    missing), masked value excerpt.  Read-only.
    """
    from harness.keys_ui import list_key_status

    status = list_key_status()
    if fmt == "json":
        import json as _json

        click.echo(_json.dumps(status, indent=2))
        sys.exit(0)
    click.echo(
        f"{'provider':<22} {'env var':<22} {'source':<10}  key (masked)               health"
    )
    click.echo("-" * 100)
    # Lazy-import per-key health so the CLI still works if Tier 2
    # modules are missing for any reason
    try:
        from harness.keys import alias_status_summary

        health_by_provider: dict[str, dict] = {}
    except ImportError:
        alias_status_summary = None
        health_by_provider = {}
    for item in status:
        source_label = item["source"]
        if source_label == "missing":
            source_styled = click.style(source_label, fg="red")
        elif source_label == "env":
            source_styled = click.style(source_label, fg="blue")
        elif source_label == "env-legacy":
            source_styled = click.style(source_label, fg="yellow")
        else:
            source_styled = click.style(source_label, fg="magenta")
        masked = item["masked"] or "(not set)"
        # Lookup per-key health if available
        health_str = ""
        if alias_status_summary and item.get("slot"):
            # Determine the env_prefix by stripping any trailing _N
            base = item["env"]
            n = item["slot"]
            prefix = (
                base.replace(f"_{n}", "")
                if base.endswith(
                    f"_{n}",
                )
                else base
            )
            if prefix not in health_by_provider:
                health_by_provider[prefix] = alias_status_summary(prefix)
            alias = f"k{n}"
            h = health_by_provider[prefix].get(alias)
            if h:
                cat = h["category"]
                if h["healthy"]:
                    health_str = click.style(cat, fg="green")
                else:
                    health_str = click.style(cat, fg="red")
            elif item["has_value"]:
                health_str = click.style("untested", fg="white", dim=True)
        click.echo(
            f"  {item['display']:<20} {item['env']:<22} "
            f"{source_styled:<19} {masked:<27} {health_str}"
        )
    sys.exit(0)


@keys_group.command(name="probe-all")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.",
)
@click.option(
    "--provider",
    "providers",
    multiple=True,
    help="Limit to specific providers (env_prefix, e.g. KIMI_API_KEY).  Default: all.",
)
def keys_probe_all(fmt: str, providers: tuple[str, ...]) -> None:
    """W14-KEYS-POOL-TIER2: live-probe every populated slot.

    For each (provider, slot) with a configured key, runs a small
    probe via ``probe_engine_live`` and records the outcome to
    ``coord/key_health.jsonl``.  Returns a table of results that
    the operator can use to identify dead/quota-exceeded keys.

    Cost: one ~5-token round-trip per populated key.  At PAYG rates
    this is well under $0.01 for a full sweep.
    """
    from harness.cli_helpers import probe_engine_live
    from harness.keys import discover_pool, record_outcome
    from harness.keys_ui import KEY_PROVIDERS

    filter_set = set(providers) if providers else None
    results = []
    for spec in KEY_PROVIDERS:
        prefix = spec["env"]
        if filter_set and prefix not in filter_set:
            continue
        engine_probe = spec.get("engine_probe", "")
        if not engine_probe:
            continue  # wrapper-only providers have no live probe
        pool = discover_pool(prefix)
        if not pool:
            results.append(
                {
                    "provider": spec["display"],
                    "env_prefix": prefix,
                    "slot": None,
                    "alias": None,
                    "category": "no-keys",
                    "up": False,
                    "error": "",
                }
            )
            continue
        for entry in pool:
            # Override the engine's primary env var temporarily
            # (the engine reads <PREFIX>, so we point it at this slot)
            prior = os.environ.get(prefix)
            os.environ[prefix] = entry.value
            try:
                category, err = probe_engine_live(engine_probe, log=False)
                up = category == "up"
                record_outcome(
                    prefix,
                    entry.alias,
                    entry.env_var,
                    category,
                    source="probe",
                    details=err or "",
                )
                results.append(
                    {
                        "provider": spec["display"],
                        "env_prefix": prefix,
                        "slot": entry.slot,
                        "alias": entry.alias,
                        "env_var": entry.env_var,
                        "label": entry.label,
                        "category": category,
                        "up": up,
                        "error": err or "",
                    }
                )
            finally:
                if prior is None:
                    os.environ.pop(prefix, None)
                else:
                    os.environ[prefix] = prior

    if fmt == "json":
        import json as _json

        click.echo(_json.dumps(results, indent=2))
        sys.exit(0)

    click.echo(f"{'provider':<22} {'slot':<6} {'alias':<6} {'category':<18} label")
    click.echo("-" * 90)
    any_down = False
    for r in results:
        cat = r["category"]
        if r["up"]:
            cat_styled = click.style(cat, fg="green")
        elif cat == "no-keys":
            cat_styled = click.style(cat, fg="white", dim=True)
        else:
            cat_styled = click.style(cat, fg="red")
            any_down = True
        slot = str(r["slot"]) if r["slot"] is not None else "—"
        alias = r["alias"] or "—"
        label = r.get("label", "") or ""
        click.echo(f"  {r['provider']:<20} {slot:<6} {alias:<6} {cat_styled:<28} {label}")

    # W14-KEYS-POOL-HARDENING 2026-05-26: auto-prune ledger so it
    # doesn't grow unbounded under cron/CI cadence.  Each (alias)
    # keeps the most recent 50 records.
    try:
        from harness.keys import prune_old_records

        summary = prune_old_records(keep_per_alias=50)
        if summary.get("dropped", 0) > 0:
            click.echo()
            click.echo(
                click.style(
                    f"  (auto-pruned {summary['dropped']} old health records; "
                    f"kept {summary['after']} most-recent per alias)",
                    fg="white",
                    dim=True,
                ),
                err=True,
            )
    except Exception:
        pass

    sys.exit(1 if any_down else 0)


@keys_group.group(name="health")
def keys_health_group() -> None:
    """W14-KEYS-POOL-HARDENING 2026-05-26: health-ledger maintenance."""


@keys_health_group.command(name="prune")
@click.option(
    "--keep-per-alias",
    type=int,
    default=50,
    show_default=True,
    help="Keep at most N most-recent records per (provider, "
    "alias).  Older entries are dropped atomically.",
)
def keys_health_prune(keep_per_alias: int) -> None:
    """W14-KEYS-POOL-HARDENING 2026-05-26: compact coord/key_health.jsonl.

    Keeps the most-recent ``--keep-per-alias`` records per (env_prefix,
    alias) pair.  Atomic rewrite under file lock.

    Cross-platform: uses msvcrt locking on Windows, fcntl on POSIX.
    Safe to run while probe-all or dispatch is also writing.

    Auto-invoked as a side effect of `harness keys probe-all`.
    """
    from harness.keys import prune_old_records

    summary = prune_old_records(keep_per_alias=keep_per_alias)
    before = summary["before"]
    after = summary["after"]
    dropped = summary["dropped"]
    aliases = summary["aliases_seen"]
    if before == 0:
        click.echo("no health records to prune (ledger empty or missing)")
    else:
        click.echo(f"  before: {before:>5} records across {aliases} alias(es)")
        click.echo(f"  after:  {after:>5} records (keep-per-alias={keep_per_alias})")
        click.echo(f"  dropped:{dropped:>5}")
    sys.exit(0)


@keys_group.group(name="policy")
def keys_policy_group() -> None:
    """W14-KEYS-POOL-TIER2: per-provider key-selection strategy."""


@keys_policy_group.command(name="get")
@click.argument("env_prefix", required=False)
def keys_policy_get(env_prefix: str) -> None:
    """Show the current strategy.  With no arg, show all providers."""
    from harness.keys import (
        DEFAULT_STRATEGY,
        get_strategy,
        list_strategies,
    )
    from harness.keys_ui import KEY_PROVIDERS

    if env_prefix:
        click.echo(get_strategy(env_prefix))
        sys.exit(0)
    all_set = list_strategies()
    click.echo(f"{'env_prefix':<25} strategy")
    click.echo("-" * 55)
    for spec in KEY_PROVIDERS:
        strat = all_set.get(spec["env"], DEFAULT_STRATEGY)
        is_default = spec["env"] not in all_set
        suffix = "  (default)" if is_default else ""
        click.echo(f"  {spec['env']:<23} {strat}{suffix}")
    sys.exit(0)


@keys_policy_group.command(name="set")
@click.argument("env_prefix")
@click.argument("strategy", type=click.Choice(["rotation", "priority", "failover-only"]))
def keys_policy_set(env_prefix: str, strategy: str) -> None:
    """Set the strategy for a provider.

    ENV_PREFIX must be a known provider (e.g. KIMI_API_KEY).
    STRATEGY must be one of rotation / priority / failover-only.
    """
    from harness.keys import set_strategy
    from harness.keys_ui import KNOWN_ENV_VARS

    if env_prefix not in KNOWN_ENV_VARS:
        click.echo(
            click.style(
                f"ERROR: unknown env_prefix {env_prefix!r}.  Known: {sorted(KNOWN_ENV_VARS)}",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)
    try:
        set_strategy(env_prefix, strategy)
    except ValueError as exc:
        click.echo(click.style(f"ERROR: {exc}", fg="red"), err=True)
        sys.exit(1)
    click.echo(f"set {env_prefix} → {strategy}")
    sys.exit(0)


@keys_group.command(name="forget")
@click.argument("env_prefix")
@click.argument("alias")
def keys_forget(env_prefix: str, alias: str) -> None:
    """W14-KEYS-POOL-TIER2: forget all health history for an alias.

    Use after manually restoring a key that was quarantined.
    Example::

        harness keys forget KIMI_API_KEY k2
    """
    from harness.keys import reset_alias_history

    n = reset_alias_history(env_prefix, alias)
    click.echo(f"dropped {n} record(s) for {env_prefix}/{alias}")
    sys.exit(0)
















@cli.group(name="audit")
def audit_group() -> None:
    """W13-AUDIT-JSONL: forensic audit trail for every dispatch.

    Append-only redacted ledger at ``~/.harness/audit.jsonl``.  Every
    call to ``harness.dispatch()`` (SDK + CLI) lands one row with
    engine, tokens, cost, retry count, and redacted prompt/response
    excerpts.  Foundation for trustworthy auto-defaults — without it,
    every auto-lens-set / auto-max-tokens / auto-retry becomes an
    un-debuggable black box.
    """


@audit_group.command(name="show")
@click.option(
    "--since-hours",
    type=float,
    default=24.0,
    help="Window in hours (default 24).  Use 0 for all-time.",
)
@click.option(
    "--engine", default=None, help="Filter by engine name (kimi/deepseek/mimo/anthropic/gemini)."
)
@click.option(
    "--tail",
    type=int,
    default=20,
    help="Show only the last N matching events (default 20). Use 0 for all matches.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.",
)
def audit_show_cmd(since_hours: float, engine: Optional[str], tail: int, fmt: str) -> None:
    """Show recent dispatch audit events (redacted)."""
    from harness.audit_jsonl import iter_events

    window = None if since_hours <= 0 else since_hours
    tail_n = None if tail <= 0 else tail
    events = iter_events(since_hours=window, engine=engine, tail=tail_n)
    if fmt == "json":
        click.echo(json.dumps(events, indent=2))
        return
    if not events:
        scope = f"in the last {since_hours:g}h" if since_hours > 0 else "all-time"
        eng_scope = f" for engine={engine!r}" if engine else ""
        click.echo(f"No audit events {scope}{eng_scope}.")
        click.echo("Ledger: ~/.harness/audit.jsonl")
        return
    for ev in events:
        ts = ev.get("ts", "?")
        eng = ev.get("engine", "?")
        ok = "ok" if ev.get("success") else "FAIL"
        tin = ev.get("tokens_in", 0)
        tout = ev.get("tokens_out", 0)
        cost = ev.get("cost_usd", 0.0)
        elapsed = ev.get("elapsed_ms", 0)
        retry = ev.get("retry_count", 0)
        retry_s = f" retry={retry}" if retry else ""
        err = ev.get("error")
        err_s = f" err={err[:60]!r}" if err else ""
        click.echo(
            f"{ts}  {eng:>10s}  {ok:>4s}  "
            f"in={tin:>5d}  out={tout:>5d}  ${cost:.4f}  "
            f"{elapsed:>6d}ms{retry_s}{err_s}"
        )


@audit_group.command(name="summary")
@click.option(
    "--since-hours",
    type=float,
    default=24.0,
    help="Window in hours (default 24).  Use 0 for all-time.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.",
)
def audit_summary_cmd(since_hours: float, fmt: str) -> None:
    """Aggregate audit events into a one-screen summary."""
    from harness.audit_jsonl import summary as audit_summary

    window = None if since_hours <= 0 else since_hours
    s = audit_summary(since_hours=window)
    if fmt == "json":
        click.echo(json.dumps(s, indent=2))
        return
    win_s = f"last {since_hours:g}h" if since_hours > 0 else "all-time"
    click.echo(f"Audit summary ({win_s}):")
    click.echo(f"  total events   : {s['total_events']}")
    click.echo(f"  successful     : {s['successful']}")
    click.echo(f"  failed         : {s['failed']}")
    click.echo(f"  retries total  : {s['retries_total']}")
    click.echo(f"  total tokens   : {s['total_tokens']}")
    click.echo(f"  total cost USD : ${s['total_cost_usd']:.4f}")
    if s["by_engine"]:
        click.echo("  by engine:")
        for eng, n in sorted(s["by_engine"].items()):
            click.echo(f"    {eng:>15s}  {n:>5d}")
    click.echo("Ledger: ~/.harness/audit.jsonl")


@audit_group.command(name="verify")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.",
)
@click.option(
    "--ledger",
    "ledger_path_str",
    type=click.Path(path_type=Path),
    default=None,
    help="Override audit ledger path (default ~/.harness/audit.jsonl).",
)
def audit_verify_cmd(fmt: str, ledger_path_str: Optional[Path]) -> None:
    """W14-AUDIT-CHAIN-HMAC: verify the chain integrity of the audit ledger.

    Walks the ledger line-by-line, recomputing each entry's HMAC-SHA256
    against the stored key + checking the prev_hash chain.  Reports the
    first tampered entry (if any) by line number.

    Exit codes:
        0 — chain verifies OK (or ledger is empty)
        1 — tampering detected, or HMAC key unavailable for verification
        2 — ledger read failed (I/O error)

    The HMAC key resolves via env var ``HARNESS_AUDIT_HMAC_KEY`` first,
    then a DPAPI-stored secret of the same name on Windows.  Use
    ``--format json`` to integrate with monitoring.
    """
    from harness.audit_chain import verify_chain
    from harness.audit_jsonl import _ledger_path

    path = _ledger_path(ledger_path_str)
    result = verify_chain(path)
    if fmt == "json":
        payload = {
            "ok": result.ok,
            "total": result.total,
            "chained": result.chained,
            "legacy": result.legacy,
            "chain_restarts": list(result.chain_restarts),
            "first_tamper_line": result.first_tamper_line,
            "reason": result.reason,
            "key_available": result.key_available,
            "ledger": str(path),
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        status = "PASS" if result.ok else "FAIL"
        click.echo(f"Audit chain verification: {status}")
        click.echo(f"  ledger          : {path}")
        click.echo(f"  total entries   : {result.total}")
        click.echo(f"  chained         : {result.chained}")
        click.echo(f"  legacy          : {result.legacy}")
        click.echo(
            f"  chain restarts  : {len(result.chain_restarts)}"
            f"{' (lines: ' + ', '.join(str(n) for n in result.chain_restarts) + ')' if result.chain_restarts else ''}"
        )
        click.echo(f"  key available   : {result.key_available}")
        if not result.ok:
            click.echo(f"  first tamper    : line {result.first_tamper_line}")
            click.echo(f"  reason          : {result.reason}")
    if not result.ok:
        raise SystemExit(1)
    if not result.key_available and result.chained == 0:
        # Empty ledger + no key — advisory, but not a hard fail
        pass


@cli.group(name="plan")
def plan_group() -> None:
    """W13-HARNESS-PLAN-VERB: surface the active strategic plan.

    The plan lives at ``coord/CURRENT_PLAN.md`` — a hand-maintained
    narrative document distilled from the most recent strategic
    planning panel.  ``coord/STATUS.csv`` is the per-row task tracker;
    this file explains WHY those rows exist + what comes after.

    A fresh agent can run ``harness plan show`` to load the current
    strategic narrative without grepping the repo.
    """


@plan_group.command(name="show")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "raw", "json"]),
    default="pretty",
    help="Output format.  'raw' prints the "
    "Markdown verbatim; 'pretty' adds "
    "a header banner; 'json' returns "
    "{path, exists, last_modified_iso, "
    "body_chars, body}.",
)
def plan_show_cmd(fmt: str) -> None:
    """Print the active strategic plan from ``coord/CURRENT_PLAN.md``."""
    from harness.plan import load_current_plan

    info = load_current_plan()
    if fmt == "json":
        click.echo(json.dumps(info, indent=2, default=str))
        return
    if not info["exists"]:
        click.echo(
            f"No plan found at {info['path']}.\n"
            f"  Create it by writing a Markdown file at that path "
            f"summarizing the active strategic plan.\n"
            f"  (See coord/reviews/ for the most recent planning panel "
            f"output if you need a starting point.)",
            err=True,
        )
        sys.exit(2)
    if fmt == "pretty":
        click.echo("=" * 60)
        click.echo(f"  Current strategic plan ({info['path']})")
        click.echo(f"  Last modified: {info['last_modified_iso']}")
        click.echo("=" * 60)
        click.echo("")
    click.echo(info["body"])


@plan_group.command(name="path")
def plan_path_cmd() -> None:
    """Print the absolute path to ``coord/CURRENT_PLAN.md``."""
    from harness.plan import plan_path

    click.echo(str(plan_path()))


@cli.command(name="capabilities")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.",
)
def capabilities_cmd(fmt: str) -> None:
    """W13 Wed-Thu bundle: show what this harness install can do.

    Cheap introspection — no engine dispatch.  Lists SDK functions,
    CLI verbs, reachable engines (by API key presence), review lens
    sets + supported extensions, and audit ledger settings.

    Designed for fresh agents asking "what does this harness know how
    to do?" without grepping the source.
    """
    from harness import capabilities as cap_fn

    cap = cap_fn()
    if fmt == "json":
        click.echo(json.dumps(cap, indent=2, default=str))
        return
    click.echo(
        f"harness v{cap.get('version', '?')} on "
        f"Python {cap.get('python_version', '?')} "
        f"({cap.get('platform', '?')})"
    )
    click.echo("")
    click.echo("SDK functions:")
    for fn in cap.get("sdk_functions", []):
        click.echo(f"  harness.{fn}()")
    click.echo("")
    click.echo("Top-level CLI verbs:")
    verbs = cap.get("cli_verbs", [])
    # 4-column display
    width = max((len(v) for v in verbs), default=0) + 2
    cols = 4
    for i in range(0, len(verbs), cols):
        click.echo("  " + "".join(v.ljust(width) for v in verbs[i : i + cols]))
    click.echo("")
    rv = cap.get("review", {})
    click.echo("Review (`harness review` / `harness.review()`):")
    click.echo(f"  lens-sets: {', '.join(rv.get('lens_sets', []))}")
    click.echo(f"  default max_tokens: {rv.get('default_max_tokens', '?')}")
    click.echo(f"  --quick max_tokens: {rv.get('quick_max_tokens', '?')}")
    exts = rv.get("supported_extensions", [])
    click.echo(
        f"  supported extensions ({len(exts)}): {', '.join(exts[:12])}"
        + (f", ...+{len(exts) - 12} more" if len(exts) > 12 else "")
    )
    click.echo("")
    eng = cap.get("engines", {})
    click.echo("Engines:")
    for name in eng.get("configured", []):
        ok = "OK" if eng.get("keys_present", {}).get(name) else "no key"
        click.echo(f"  {name:<12s} {ok}")
    click.echo("")
    aud = cap.get("audit", {})
    click.echo("Audit:")
    click.echo(f"  ledger: {aud.get('ledger_path', '?')}")
    click.echo(f"  retention: {aud.get('max_age_days', '?')} days")




@cli.command(name="today")
@click.option(
    "--since-hours", type=int, default=24, help="How far back to look for activity (default 24)."
)
def today_cmd(since_hours: int) -> None:
    """W8-STATUS-HUMAN: plain-language daily pulse for the operator.

    Shows three sections in plain English:
      1. Overnight summary — what shipped, what audited
      2. Current blockers — preflight + observer flags + dead engines
      3. Next 1-3 actions — what the operator should do today

    Designed for the non-technical operator (per
    [[user_non_technical_role]] memory): no UUIDs, no commit hashes,
    no Python tracebacks unless explicitly part of an error message.
    """
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    repo = Path.cwd()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    click.echo("=" * 60)
    click.echo(f"  Today — what happened in the last {since_hours} hours")
    click.echo("=" * 60)

    # Section 1: overnight summary
    click.echo("\n## What shipped\n")
    shipped_today: list[str] = []
    try:
        csv_path = repo / "coord" / "STATUS.csv"
        if csv_path.exists():
            import csv as _csv

            with csv_path.open("r", encoding="utf-8", newline="") as fh:
                reader = _csv.DictReader(fh)
                for row in reader:
                    if row.get("Status") != "shipped":
                        continue
                    updated = row.get("Updated", "")
                    # Crude date parse — Updated is "2026-05-23" format
                    try:
                        when = datetime.fromisoformat(updated + "T00:00:00+00:00")
                    except ValueError:
                        continue
                    if when >= cutoff:
                        title = row.get("Title", "(no title)")
                        shipped_today.append(f"  {row.get('ID', '?')} — {title}")
    except Exception:
        shipped_today = []
    if shipped_today:
        for line in shipped_today[:12]:
            click.echo(line)
        if len(shipped_today) > 12:
            click.echo(f"  ... and {len(shipped_today) - 12} more")
    else:
        click.echo("  (nothing shipped in this window)")

    # Section 1.5: audit results in this window
    click.echo("\n## Audit results (recent reviews)\n")
    audit_dir = repo / "coord" / "reviews" / "audits"
    audit_count = {"pass": 0, "stop": 0}
    recent_audits: list[tuple[str, str, float]] = []
    if audit_dir.exists():
        for audit_file in sorted(
            audit_dir.glob("*_audit.md"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                mtime = datetime.fromtimestamp(
                    audit_file.stat().st_mtime,
                    tz=timezone.utc,
                )
            except OSError:
                continue
            if mtime < cutoff:
                continue
            try:
                head = audit_file.read_text(encoding="utf-8")[:500]
            except OSError:
                continue
            import re as _re

            conf_m = _re.search(r"confidence=([0-9.]+)", head)
            task_m = _re.search(r"task=([^\s]+)", head)
            if conf_m and task_m:
                conf = float(conf_m.group(1))
                if conf >= 0.7:
                    audit_count["pass"] += 1
                else:
                    audit_count["stop"] += 1
                recent_audits.append((task_m.group(1), audit_file.name, conf))
    if recent_audits:
        click.echo(
            f"  {audit_count['pass']} PASS, "
            f"{audit_count['stop']} STOP, "
            f"total {len(recent_audits)} in this window"
        )
        for task, _, conf in recent_audits[:6]:
            verdict = "PASS" if conf >= 0.7 else "STOP"
            click.echo(f"    {verdict:<4} {conf:.2f}  {task}")
        if len(recent_audits) > 6:
            click.echo(f"    ... and {len(recent_audits) - 6} more")
    else:
        click.echo("  (no audits ran in this window)")

    # Section 1.6: W12-LOOP-STALENESS-WATCHDOG — surface the dev-loop's
    # own staleness.  The 20-agent panel found the dashboard claiming
    # "Loop: armed" while last tick was 3 days ago.  Honest 'today'
    # output must flag this so operator notices a dead loop.
    # Loop health + L5 observer-escalation sections retired (PATH-A-TRIM
    # 2026-05-29): the autonomous dev-loop + observer machinery was deleted
    # in the harness retirement to a thin ask/proxy/keys core.

    # Section 2: current blockers
    click.echo("\n## Current blockers\n")
    blockers: list[str] = []
    try:
        # Skip engines — would burn API spend on every `harness today`
        from harness import preflight as _pf
        from concurrent.futures import ThreadPoolExecutor, as_completed

        pairs = [(n, fn) for n, fn in _pf._all_check_callables() if not n.startswith("engine:")]
        pre_results = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fn): name for name, fn in pairs}
            for f in as_completed(futures):
                try:
                    pre_results.append(f.result())
                except Exception:
                    pass
        for r in pre_results:
            if r.severity == "fail":
                blockers.append(f"  [X] {r.name}: {r.message}")
            elif r.severity == "warn":
                blockers.append(f"  [!] {r.name}: {r.message}")
    except Exception as exc:
        blockers.append(f"  (couldn't run preflight: {exc})")
    # Observer flags
    flags_dir = repo / "coord" / "observer" / "flags"
    if flags_dir.exists():
        high_flags = list(flags_dir.glob("*high*.md"))
        if high_flags:
            blockers.append(
                f"  [!] {len(high_flags)} HIGH observer flag(s) — run `harness observer flags`"
            )
    if blockers:
        for b in blockers[:8]:
            click.echo(b)
        if len(blockers) > 8:
            click.echo(f"  ... and {len(blockers) - 8} more")
    else:
        click.echo("  None — preflight is green.")

    # Section 2.5: capabilities surface (W13 Wed-Thu bundle)
    # One-line install snapshot so a fresh agent / operator sees what
    # this binary can do without firing `harness capabilities` separately.
    click.echo("\n## Install + capabilities\n")
    try:
        from harness import capabilities as _cap_fn

        cap = _cap_fn()
        eng_keys = cap.get("engines", {}).get("keys_present", {})
        eng_ok = sorted(k for k, v in eng_keys.items() if v)
        eng_missing = sorted(k for k, v in eng_keys.items() if not v)
        click.echo(
            f"  harness v{cap.get('version', '?')} on "
            f"Python {cap.get('python_version', '?')} "
            f"({cap.get('platform', '?')})"
        )
        click.echo(
            f"  Engines reachable: {', '.join(eng_ok) if eng_ok else '(none — set API keys)'}"
        )
        if eng_missing:
            click.echo(
                f"  Engines unreachable: {', '.join(eng_missing)} (set the *_API_KEY env vars)"
            )
        click.echo(f"  Audit ledger: {cap.get('audit', {}).get('ledger_path', '?')}")
        click.echo(f"  SDK: {', '.join(cap.get('sdk_functions', [])) or '(none)'}")
        click.echo("  Run `harness capabilities` for the full dict.")
    except Exception as exc:
        click.echo(f"  (capabilities introspection failed: {exc})")

    # Section 3: next 1-3 actions
    click.echo("\n## Suggested next actions\n")
    suggestions: list[str] = []
    has_fail = any("[X]" in b for b in blockers)
    has_warn = any("[!]" in b for b in blockers)
    if has_fail:
        suggestions.append(
            "  1. Run `harness preflight --fix --dry-run` "
            "to preview the auto-fix, then drop --dry-run."
        )
    if has_warn and not has_fail:
        suggestions.append(
            "  1. `harness preflight --fix` for the warnings (or ignore — warnings don't block)."
        )
    if not has_fail and not has_warn:
        if audit_count.get("stop", 0) > 0:
            suggestions.append(
                "  1. Review the STOP audits in "
                "`coord/reviews/audits/` — they need operator decision."
            )
        else:
            suggestions.append(
                "  1. Loop is green.  Skim `harness morning-brief` for the "
                "narrative, then go do non-harness work."
            )
    suggestions.append(
        "  2. If anything looks wrong, run `harness panic-dump` and ping engineering."
    )
    for s in suggestions:
        click.echo(s)

    click.echo(f"\n{'=' * 60}")
    click.echo("  For the full daily playbook: docs/OPERATOR_RUNBOOK.md")
    click.echo(f"{'=' * 60}\n")








@cli.group(name="advanced")
def advanced_group() -> None:
    """W11-HIDE-ADVANCED-VERBS: list + invoke engineering-tier verbs.

    The default `harness --help` hides the operator-engineering
    verbs (lint-spec, panic-dump, swarm-verify, engines-reliability,
    burst, lock, replay, proxy) to keep the surface focused on
    daily-use commands.

    Use `harness advanced list` to see the hidden verbs, or invoke
    them directly via their original verb name (e.g. `harness replay
    <task-id>`) — hiding only affects help-text discovery, not callability.
    """


@advanced_group.command(name="list")
def advanced_list() -> None:
    """List the engineering-tier verbs hidden from default --help."""
    # Walk cli.commands looking for hidden=True
    hidden_cmds: list[tuple[str, str]] = []
    for name, cmd in sorted(cli.commands.items()):
        if getattr(cmd, "hidden", False):
            help_text = (cmd.help or cmd.short_help or "").strip()
            help_text = help_text.split("\n")[0][:70]
            hidden_cmds.append((name, help_text))
    if not hidden_cmds:
        click.echo("(no hidden verbs registered)")
        return
    click.echo("Engineering-tier verbs (hidden from default --help):\n")
    width = max(len(n) for n, _ in hidden_cmds)
    for name, help_text in hidden_cmds:
        click.echo(f"  {name:<{width}}  {help_text}")
    click.echo(
        "\nInvoke via `harness <verb>` — hidden only affects help discovery, not callability."
    )














@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("subcmd", required=False)
@click.argument("subcmd_args", nargs=-1)
@click.option("--list", "list_", is_flag=True, help="List engines.")
@click.option(
    "--health",
    is_flag=True,
    help="Check engine health (live dispatch probe by default; --shallow for network-only check).",
)
@click.option(
    "--shallow",
    is_flag=True,
    help="With --health, use the legacy network-GET probe instead of a real dispatch probe.",
)
@click.option(
    "--since-hours",
    type=int,
    default=168,
    help="With 'engines failures' subcommand, look back this many hours (default 168 = 7 days).",
)
@click.option(
    "--engine",
    "engine_filter",
    default=None,
    help="With 'engines failures' subcommand, restrict to one engine.",
)
def engines(
    subcmd: str | None,
    subcmd_args: tuple[str, ...],
    list_: bool,
    health: bool,
    shallow: bool,
    since_hours: int,
    engine_filter: str | None,
) -> None:
    """Query or modify the engine pool.

    Subcommands:
      list             — show priority/locked/status per engine (default)
      health           — live-dispatch probe categorizing each engine's
                         state (terminated/auth-failed/quota-exceeded/...)
      heal             — re-issue the in-memory engine health state
      failures         — read state/engine_performance_log.jsonl +
                         state/engine_health_probes.jsonl, aggregate
                         failure counts by category per engine
      install-wrappers — install per-provider claude-* wrapper scripts
      list-wrappers    — show installed wrappers + their key status
      fallback-policy  — show effective fallback chain + skip reasons
      describe <name>  — W14-ENGINE-METADATA 2026-05-28 — emit structured
                         metadata for an engine: protocol surfaces, key
                         prefixes, UA gating, recommended task classes,
                         latency class, cost, consumption surfaces.
                         Pass `json` as the 2nd arg for JSON output.
      compatibility-matrix
                       — N×M table of engines × consumption surfaces
                         (http_direct / proxy_upstream / pattern_b /
                         swarm).  Pass `--json` for machine output.
      recommend <cls>  — W14-CROSS-ENGINE-AUDIT 2026-05-26 — print the
                         recommended Pattern B engine for a task class.
                         Valid classes: default/latency/verbose/cost/
                         multimodal/audit.  Engine name on stdout
                         (pipe-friendly); rationale on stderr.

    W13-ENGINE-FAILURE-VISIBILITY 2026-05-25: ``engines --health`` now
    defaults to a real dispatch probe (~5 tokens per engine).  The
    legacy network-GET probe — which marks any HTTP response as "up",
    including 403 "Access terminated" — is still available via the
    ``--shallow`` flag.  The live probe catches account-termination,
    quota-exhaustion, and key-revocation cases that the shallow probe
    misses.
    """
    # Normalise subcommand-style guesses into flag-style
    if subcmd == "list":
        list_ = True
    elif subcmd == "health":
        health = True
    elif subcmd == "install-wrappers":
        # W14-CLAUDE-CODE-WRAPPER-SCRIPTS: install per-provider wrappers
        from harness.engines.wrapper_scripts import (
            DEFAULT_WRAPPER_DIR,
            get_path_hint,
            install_wrappers,
        )

        click.echo(f"Installing claude-* wrapper scripts to {DEFAULT_WRAPPER_DIR}...")
        result = install_wrappers()
        for name, info in result.items():
            status = info.get("status", "?")
            path = info.get("path", "-")
            if status == "installed":
                color = "green"
                badge = "INSTALLED"
            elif status == "skipped-exists":
                color = "cyan"
                badge = "EXISTS"
            else:
                color = "yellow"
                badge = "SKIPPED"
            badge_styled = click.style(badge, fg=color, bold=True)
            click.echo(f"  {badge_styled:<18}  {name:<22}  {path}")
        hint = get_path_hint()
        if hint:
            click.echo()
            click.echo(
                click.style(
                    "NOTE: wrapper dir is not on your PATH.",
                    fg="yellow",
                    bold=True,
                )
            )
            click.echo(hint)
        else:
            click.echo()
            click.echo(
                click.style(
                    "Wrappers ready — use them like 'claude-mimo \"your prompt\"'",
                    fg="green",
                )
            )
        sys.exit(0)
    elif subcmd == "list-wrappers":
        from harness.engines.wrapper_scripts import list_wrappers

        wrappers = list_wrappers()
        click.echo(f"{'wrapper':<22} {'installed':<10} {'key set':<8}  description")
        click.echo("-" * 80)
        for w in wrappers:
            inst = click.style(
                "yes" if w["installed"] else "no",
                fg="green" if w["installed"] else "red",
            )
            key = click.style(
                "yes" if w["key_present"] else "no",
                fg="green" if w["key_present"] else "yellow",
            )
            click.echo(f"  {w['name']:<20} {inst:<19} {key:<17}  {w['description']}")
        sys.exit(0)
    elif subcmd == "fallback-policy":
        # W14-DISPATCH-HEALTH-AWARE-FALLBACK: show the effective fallback
        # order (priority-sorted, matches dispatcher runtime) with skip
        # reasons (no-key / terminated / over-cap).
        from harness.engines.routing import describe_fallback_policy

        policy = describe_fallback_policy()
        click.echo(f"Filter enabled: {not policy['filter_disabled']}")
        click.echo(f"All production engines: {', '.join(policy['all_engines'])}")
        click.echo()
        if policy["eligible_with_priority"]:
            click.echo("Eligible for dispatch (priority-sorted, tie = SUPPORTED_BACKENDS order):")
            for entry in policy["eligible_with_priority"]:
                # Mark non-NORMAL priorities to make explicit decisions visible
                if entry["priority"] == "HIGH":
                    badge = click.style("HIGH", fg="green", bold=True)
                elif entry["priority"] == "AVOID":
                    badge = click.style("AVOID", fg="yellow")
                else:
                    badge = "NORMAL"
                click.echo(f"  ✓ {entry['engine']:<10}  priority={badge}")
            click.echo()
            click.echo(
                "(All-NORMAL ties resolve by SUPPORTED_BACKENDS "
                "order; use 'harness priority <engine> HIGH' to "
                "bump an engine above the tie.)"
            )
        else:
            click.echo("(no engines eligible — check API keys + budget caps)")
        if policy["skipped"]:
            click.echo()
            click.echo("Skipped engines:")
            for eng, reason in sorted(policy["skipped"].items()):
                click.echo(f"  ✗ {eng}: {reason}")
        sys.exit(0)
    elif subcmd == "describe":
        # W14-ENGINE-METADATA 2026-05-28: queryable per-engine metadata.
        # Replaces N tool-calls of source-spelunking with 1 call.
        # Surfaces protocol surfaces, UA gating, key prefixes,
        # recommended task classes, latency class, cost reference,
        # consumption-surface compatibility.
        from harness.engines.metadata import describe as _describe

        engine_name = subcmd_args[0] if subcmd_args else ""
        if not engine_name:
            from harness.engines.metadata import list_engine_metadata

            click.echo(
                click.style(
                    "ERROR: harness engines describe requires an engine "
                    "name argument.  Known: " + ", ".join(sorted(list_engine_metadata())),
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)
        # JSON via --format flag would be nice; for now just check the
        # arg has "--json" or "json" as second positional
        as_json = "--json" in subcmd_args or "json" in subcmd_args[1:2]
        try:
            md = _describe(engine_name)
        except ValueError as e:
            click.echo(click.style(f"ERROR: {e}", fg="red"), err=True)
            sys.exit(2)
        if as_json:
            import json
            from dataclasses import asdict

            click.echo(json.dumps(asdict(md), indent=2))
            sys.exit(0)
        # Human-readable text format
        click.echo(click.style(f"# {md.name}", fg="cyan", bold=True))
        click.echo(f"  vendor:       {md.vendor}")
        click.echo(f"  description:  {md.description}")
        click.echo()
        click.echo(click.style("Protocol + key", fg="yellow", bold=True))
        click.echo(f"  surfaces:     {', '.join(md.protocol_surfaces)}")
        click.echo(f"  key env:      {md.key_env}")
        if md.key_prefixes:
            click.echo(f"  key prefixes: {', '.join(md.key_prefixes)}")
        if md.ua_gating:
            click.echo()
            click.echo(
                click.style(
                    "⚠ UA gating:",
                    fg="yellow",
                    bold=True,
                )
            )
            for line in md.ua_gating.splitlines():
                click.echo(f"  {line}")
        click.echo()
        click.echo(click.style("Models", fg="yellow", bold=True))
        click.echo(f"  default:      {md.default_model}")
        if md.available_models:
            click.echo(f"  available:    {', '.join(md.available_models)}")
        click.echo()
        click.echo(click.style("Performance", fg="yellow", bold=True))
        click.echo(f"  latency:      {md.latency_class}")
        if md.cost_per_smoke_usd:
            click.echo(f"  cost/smoke:   ${md.cost_per_smoke_usd:.4f}")
        if md.recommended_task_classes:
            click.echo(f"  best for:     {', '.join(md.recommended_task_classes)}")
        click.echo()
        click.echo(click.style("How to reach", fg="yellow", bold=True))
        for surface, note in md.consumption_surfaces.items():
            click.echo(f"  {surface:<18} {note}")
        if md.notes:
            click.echo()
            click.echo(click.style("Notes", fg="yellow", bold=True))
            for line in md.notes.splitlines():
                click.echo(f"  {line}")
        sys.exit(0)
    elif subcmd == "compatibility-matrix":
        from harness.engines.metadata import compatibility_matrix

        rows = compatibility_matrix()
        as_json = "--json" in subcmd_args
        if as_json:
            import json

            click.echo(json.dumps(rows, indent=2))
            sys.exit(0)
        # Render text table
        click.echo(
            click.style(
                "Engine compatibility matrix (engines × consumption surfaces)",
                fg="cyan",
                bold=True,
            )
        )
        click.echo()
        for r in rows:
            ua_badge = click.style(" [UA-gated]", fg="yellow") if r["ua_gated"] else ""
            click.echo(
                click.style(f"  {r['engine']}", bold=True)
                + f"  ({r['vendor']}; protocols: "
                + ", ".join(r["protocols"])
                + ")"
                + ua_badge
            )
            click.echo(f"    http_direct      {r['http_direct']}")
            click.echo(f"    proxy_upstream   {r['proxy_upstream']}")
            click.echo(f"    pattern_b        {r['pattern_b']}")
            click.echo(f"    swarm            {r['swarm']}")
            click.echo()
        click.echo(
            click.style(
                "  Tip: `harness engines describe <name>` for full metadata on any engine.",
                fg="white",
                dim=True,
            )
        )
        sys.exit(0)
    elif subcmd == "recommend":
        # W14-CROSS-ENGINE-AUDIT 2026-05-26: programmatic routing
        # recommendations from the empirical smoke matrix.  See
        # spec/engine-routing-empirical.md for the data + rationale.
        #
        # Usage:  harness engines recommend <task-class>
        # Valid:  default | latency | verbose | cost | multimodal | audit
        from harness.engines.routing_recommend import (
            VALID_TASK_CLASSES,
            recommend as _recommend,
        )

        task_class = subcmd_args[0] if subcmd_args else ""
        if not task_class:
            click.echo(
                click.style(
                    "ERROR: harness engines recommend requires a "
                    "task-class argument.  Valid: " + ", ".join(sorted(VALID_TASK_CLASSES)),
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)
        rec = _recommend(task_class)
        # Print engine on stdout (pipe-friendly).  Rationale + alternates
        # on stderr so callers can `$(harness engines recommend default)`.
        click.echo(rec.engine)
        if rec.model_override:
            click.echo(
                click.style(
                    f"  (model_override: {rec.model_override})",
                    fg="cyan",
                    dim=True,
                ),
                err=True,
            )
        click.echo(
            click.style(f"  rationale: {rec.rationale}", fg="white", dim=True),
            err=True,
        )
        if rec.alternates:
            click.echo(
                click.style(
                    f"  alternates: {', '.join(rec.alternates)}",
                    fg="white",
                    dim=True,
                ),
                err=True,
            )
        sys.exit(0)
    elif subcmd == "failures":
        from harness.cli_helpers import read_failure_summary

        summary = read_failure_summary(
            since_hours=since_hours,
            engine=engine_filter,
        )
        if not summary["engines"]:
            click.echo(
                f"No engine events in the last {since_hours}h"
                + (f" for {engine_filter}" if engine_filter else "")
                + "."
            )
            sys.exit(0)
        click.echo(f"Engine failure summary (last {since_hours}h):")
        for eng_name, slot in sorted(summary["engines"].items()):
            total = slot["total"]
            by_cat = slot["by_category"]
            failures = sum(v for k, v in by_cat.items() if k != "up")
            click.echo(
                f"\n  {eng_name}: {total} events"
                f" ({failures} failures, "
                f"{by_cat.get('up', 0)} successes)"
            )
            for cat in sorted(by_cat, key=lambda c: -by_cat[c]):
                if cat == "up":
                    continue
                click.echo(f"    {cat:<18} {by_cat[cat]}")
            if slot["recent_samples"]:
                click.echo("    recent samples:")
                for s in slot["recent_samples"]:
                    excerpt = (s.get("error_excerpt") or "")[:80]
                    click.echo(
                        f"      {s['timestamp']} {s['category']:<14} ({s['source']}) {excerpt}"
                    )
        sys.exit(0)
    elif subcmd == "heal":
        from click.testing import CliRunner as _CR  # local import OK

        runner = _CR()
        ctx = click.get_current_context()
        ctx.invoke(engines_heal_cmd, dry_run=False, engine=None)
        return
    elif subcmd is not None:
        click.echo(
            f"Error: unknown subcommand {subcmd!r}; use 'list', "
            f"'health', 'failures', or 'heal' "
            f"(or --list / --health flags)",
            err=True,
        )
        sys.exit(2)

    state = read_engine_health()

    if health:
        if shallow:
            probes = probe_all_engines()
        else:
            from harness.cli_helpers import probe_all_engines_live

            probes = probe_all_engines_live()
        for name, (st, err) in probes.items():
            click.echo(f"{name}: {st}" + (f" ({err})" if err else ""))
        sys.exit(0)

    # Default / --list
    for name in ["deepseek", "kimi", "mimo", "anthropic", "gemini"]:
        cfg = state.get(name)
        if cfg:
            click.echo(f"{name}: priority={cfg.priority} locked={cfg.locked} status={cfg.status}")
        else:
            click.echo(f"{name}: priority=NORMAL locked=False status=up")
    sys.exit(0)


@cli.command(name="engines-reliability", hidden=True)
@click.option(
    "--publish", is_flag=True, help="Write coord/engine_reliability.json from latest campaigns."
)
def engines_reliability(publish: bool) -> None:
    """Show / publish engine reliability ranking from campaign data.

    W5-C 2026-05-22: aggregates W4-G campaign outputs into a parseable-rate
    ranking per engine.  The dispatcher consults this at fallback-time to
    prefer engines that have shown empirical reliability over the
    hardcoded chain.
    """
    from harness.engines.reliability import (
        aggregate_campaigns,
        publish as publish_digest,
        load_published,
    )

    if publish:
        out = publish_digest()
        click.echo(f"published reliability digest to {out}")
        # fall through to display it

    digest = aggregate_campaigns() if not publish else load_published()
    if digest is None or not digest.ranking:
        click.echo("(no reliability data yet — run scripts/multi_agent_coverage.py)", err=True)
        sys.exit(1 if not publish else 0)

    click.echo(f"# engine reliability  (campaigns={len(digest.source_campaigns)})")
    click.echo(f"{'engine':10} {'model':22} {'ok':>4} {'fail':>4} {'rate':>6} {'avg_lat_ms':>10}")
    for r in digest.ranking:
        click.echo(
            f"{r.engine:10} {(r.model or ''):22} "
            f"{r.ok:>4} {r.fail:>4} "
            f"{r.parseable_rate:>5.1%} {r.avg_latency_ms:>10}"
        )
    sys.exit(0)


@cli.command(name="engines-heal")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Preview what would happen without applying."
)
@click.option("--engine", default=None, help="Heal only this engine (default: all dead engines).")
def engines_heal_cmd(dry_run: bool, engine: str | None) -> None:
    """W8-ENGINES-HEAL: one-command recovery for dead / quarantined engines.

    Walks the dead-engine alarm state (W6-C2) plus the engine health
    file and:
      1. Quarantines engines currently above the failure threshold.
      2. Attempts to reload API keys from DPAPI for each quarantined
         engine — if the key is back, mark it ``recovering`` so the
         dispatcher gives it one more attempt.
      3. Surfaces a plain-language report.

    Designed for the non-technical operator (per
    [[user_non_technical_role]] + readiness panel feedback 4/10 vote).
    No Python tracebacks, no JSONL paths — operator-friendly only.

    To reset an engine manually later, run ``harness engines reset
    <name>`` (or ``priority <name> NORMAL`` if you'd rather route to
    it).
    """
    from harness.engine_alarm import dead_engines as _dead
    from harness.state.files import read_engine_health, update_engine_health
    from harness.secrets import dpapi
    from harness._constants import API_KEY_ENV_VARS

    click.echo("=" * 60)
    click.echo("  harness engines-heal — automated engine recovery")
    click.echo("=" * 60)
    if dry_run:
        click.echo("\nDRY RUN — no changes will be applied.\n")

    # 1) Find dead engines (from the alarm) + currently-quarantined
    # ones (from engine_health).
    try:
        dead_streaks = _dead()
    except Exception as exc:
        click.echo(f"  [X] Couldn't read engine alarm state: {exc}", err=True)
        sys.exit(2)
    try:
        health = read_engine_health()
    except Exception as exc:
        click.echo(f"  [X] Couldn't read engine health: {exc}", err=True)
        sys.exit(2)

    # W8-AUDIT follow-through 2026-05-24: read_engine_health returns
    # Pydantic EngineHealth objects in production but tests stub it with
    # raw dicts — handle both so the quarantined detection actually
    # fires in both contexts.
    def _entry_status(entry: Any) -> str | None:
        if isinstance(entry, dict):
            return entry.get("status")
        return getattr(entry, "status", None)

    quarantined_now = {
        name for name, entry in (health or {}).items() if _entry_status(entry) == "quarantined"
    }
    affected = set(dead_streaks.keys()) | quarantined_now
    if engine:
        affected = {e for e in affected if e == engine}
        if not affected:
            click.echo(
                f"  [OK] Engine '{engine}' is not in the dead or quarantined set — nothing to heal."
            )
            sys.exit(0)
    if not affected:
        click.echo("\n  [OK] All engines are healthy — nothing to heal.")
        click.echo("\n  Tip: `harness engines-reliability` shows the full")
        click.echo("       ranking if you want a deeper look.\n")
        sys.exit(0)

    click.echo(f"\n  Found {len(affected)} engine(s) needing attention:\n")
    actions: list[tuple[str, str, str]] = []  # (engine, action, message)
    for e in sorted(affected):
        streak = dead_streaks.get(e, 0)
        was_quarantined = e in quarantined_now
        # 2) Probe DPAPI for the engine's API key
        env_var = API_KEY_ENV_VARS.get(e, "").upper()
        key_present = False
        if env_var:
            try:
                key_present = dpapi.has_secret(env_var)
            except Exception:
                key_present = False
        if streak > 0 and not was_quarantined:
            # Newly dead — quarantine
            if dry_run:
                actions.append(
                    (
                        e,
                        "would-quarantine",
                        f"Hit {streak} consecutive failures.  "
                        f"Would quarantine.  Key in DPAPI: "
                        f"{'YES' if key_present else 'no'}.",
                    )
                )
            else:
                try:
                    update_engine_health(
                        e,
                        {
                            "status": "quarantined",
                            "last_quarantine": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    actions.append(
                        (
                            e,
                            "quarantined",
                            f"Quarantined after {streak} consecutive "
                            f"failures.  Key in DPAPI: "
                            f"{'YES' if key_present else 'no'}.",
                        )
                    )
                except Exception as exc:
                    actions.append(
                        (
                            e,
                            "error",
                            f"Tried to quarantine but couldn't update engine health: {exc}",
                        )
                    )
        elif was_quarantined and key_present:
            # Already quarantined + key is present in DPAPI → mark
            # recovering so the dispatcher tries it once.
            if dry_run:
                actions.append(
                    (
                        e,
                        "would-recover",
                        "Already quarantined.  Key in DPAPI is present.  "
                        "Would mark as 'recovering' for one retry.",
                    )
                )
            else:
                try:
                    update_engine_health(
                        e,
                        {
                            "status": "recovering",
                            "last_heal_attempt": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    actions.append(
                        (
                            e,
                            "recovering",
                            "Marked as 'recovering' — dispatcher will "
                            "give it one more attempt.  If it succeeds, "
                            "it auto-promotes back to 'ok'.",
                        )
                    )
                except Exception as exc:
                    actions.append(
                        (
                            e,
                            "error",
                            f"Tried to mark recovering but failed: {exc}",
                        )
                    )
        elif was_quarantined and not key_present:
            actions.append(
                (
                    e,
                    "blocked",
                    "Quarantined and no API key found in DPAPI.  Engine "
                    "needs a fresh key — run `harness install` to seed it, "
                    "OR set the env var and re-run engines-heal.",
                )
            )
        else:
            actions.append(
                (
                    e,
                    "watch",
                    f"Currently above failure threshold ({streak} streak) "
                    "but not yet quarantined.  Will be picked up on next "
                    "dispatch.  Re-run engines-heal in a few minutes if "
                    "this persists.",
                )
            )

    glyph = {
        "quarantined": "[FIXED]",
        "would-quarantine": "[!]",
        "recovering": "[FIXED]",
        "would-recover": "[!]",
        "blocked": "[X]",
        "watch": "[!]",
        "error": "[X]",
    }
    for e, action, msg in actions:
        g = glyph.get(action, "[?]")
        click.echo(f"  {g} {e:<12} {action:<18} {msg}")
        if action in {"quarantined", "recovering"}:
            click.echo(f"          undo: harness engines reset {e}  (or  priority {{e}} NORMAL)")
    click.echo("=" * 60)
    if dry_run:
        click.echo("\n  Preview only — nothing changed.")
        click.echo("  Re-run without --dry-run to apply.\n")
    else:
        applied = sum(1 for _, a, _ in actions if a in {"quarantined", "recovering"})
        blocked = sum(1 for _, a, _ in actions if a == "blocked")
        click.echo(
            f"\n  Healed {applied}; blocked {blocked}; to-watch {len(actions) - applied - blocked}."
        )
        if blocked:
            click.echo(
                "\n  Blocked engines need a fresh API key.  "
                "Ask your engineering teammate or run "
                "`harness install` to seed.\n"
            )
        else:
            click.echo("")
    sys.exit(0)








# ---------------------------------------------------------------------------
# Heartbeat (HEARTBEAT — roster row #17)
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# State inspector (STATE-INSPECT — roster row #18 companion)
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# Replay (REPLAY-CLI — decision archaeology for dispatches)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Budget (BUDGET-METER — dispatch cost ledger)
# ---------------------------------------------------------------------------


def _budget_archive_dir() -> Path:
    return Path("coord/dev_loop/budget_archive")


@cli.group(name="budget")
def budget_group() -> None:
    """Dispatch budget + per-engine cost ledger."""


@budget_group.command(name="show")
@click.option("--engine", default=None)
@click.option("--since", default=None, help="ISO timestamp filter")
def budget_show(engine: Optional[str], since: Optional[str]) -> None:
    """Tabular ledger output.

    Rows where ``cost_known=False`` (unpriced engine — typically a model
    rename that hasn't been added to the pricing table) are tagged
    ``[UNPRICED]`` so the operator sees the meter is undercounting.
    P3 audit fix 2026-05-27.
    """
    entries = read_ledger(DEFAULT_LEDGER_PATH)
    if since:
        entries = [e for e in entries if e.timestamp >= since]
    if engine:
        entries = [e for e in entries if e.engine == engine]
    if not entries:
        click.echo("(no entries)")
        sys.exit(0)
    unpriced_count = 0
    for e in entries:
        tag = " [UNPRICED]" if not e.cost_known else ""
        if not e.cost_known:
            unpriced_count += 1
        click.echo(f"{e.timestamp}  {e.engine:12}  {e.task_id:20}  ${e.cost_usd:.6f}{tag}")
    if unpriced_count:
        click.echo()
        click.echo(
            f"WARN: {unpriced_count} of {len(entries)} dispatches show "
            f"as UNPRICED (engine not in pricing table; cost meter "
            f"undercounts).  See: harness budget summary"
        )
    sys.exit(0)


@budget_group.command(name="summary")
@click.option("--since", default=None)
@click.option(
    "--since-days",
    type=int,
    default=None,
    help="Number of days to look back (mutually exclusive with --since).",
)
def budget_summary_cmd(since: str | None, since_days: int | None) -> None:
    """Per-engine totals + grand total."""
    if since is not None and since_days is not None:
        raise click.UsageError("--since and --since-days are mutually exclusive")
    if since_days is not None and since_days < 1:
        raise click.BadParameter("--since-days must be >= 1", param_hint="'--since-days'")
    if since_days is not None:
        since_iso = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    elif since is not None:
        since_iso = since
    else:
        since_iso = datetime.now(timezone.utc).strftime("%Y-%m")
    agg = budget_summary(DEFAULT_LEDGER_PATH, since_iso=since_iso)
    if not agg:
        click.echo("(no dispatches)")
        sys.exit(0)
    total = 0.0
    unpriced_total = 0
    unpriced_engines: list[str] = []
    for eng, data in sorted(agg.items()):
        # P3 audit fix 2026-05-27: surface unpriced dispatches inline so
        # the operator sees the meter is undercounting per engine.
        unpriced_n = int(data.get("unpriced_dispatches", 0))
        unpriced_suffix = ""
        if unpriced_n:
            unpriced_suffix = f"  [{unpriced_n} UNPRICED - cost meter incomplete]"
            unpriced_total += unpriced_n
            unpriced_engines.append(eng)
        click.echo(
            f"{eng:12}  dispatches={int(data['dispatches'])}  "
            f"cost=${data['total_cost_usd']:.6f}  "
            f"in={int(data['total_input_tokens'])}  "
            f"out={int(data['total_output_tokens'])}{unpriced_suffix}"
        )
        total += data["total_cost_usd"]
    click.echo(f"{'total':12}  ${total:.6f}")
    if unpriced_total:
        click.echo()
        click.echo(
            f"WARN: {unpriced_total} unpriced dispatch(es) across "
            f"engine(s) {', '.join(unpriced_engines)} - cost meter "
            f"under-reports total spend.  Add these engines to "
            f"PRICING_USD_PER_M_TOKENS in src/harness/budget.py "
            f"(or set HARNESS_BUDGET_PRICING_JSON) to fix."
        )
    sys.exit(0)


@budget_group.command(name="by-run")
@click.option(
    "--since", default=None, help="ISO-8601 timestamp lower bound (e.g. 2026-05-22T00:00:00Z)."
)
@click.option(
    "--since-days",
    type=int,
    default=None,
    help="Look back N days (mutually exclusive with --since).",
)
@click.option(
    "--top", type=int, default=20, help="Show only the top N most-expensive runs (default 20)."
)
def budget_by_run(since: str | None, since_days: int | None, top: int) -> None:
    """Per-run cost rollup using W4-K token tracking.

    Groups ledger entries by `task_id` (which is the coord run-id for
    worker-spawned dispatches) and shows tokens + cost per run.  Useful
    for "did this overnight run blow my budget?" answer.
    """
    if since is not None and since_days is not None:
        raise click.UsageError("--since and --since-days are mutually exclusive")
    if since_days is not None and since_days < 1:
        raise click.BadParameter("--since-days must be >= 1", param_hint="'--since-days'")

    entries = read_ledger(DEFAULT_LEDGER_PATH)
    if since_days is not None:
        threshold = datetime.now(timezone.utc) - timedelta(days=since_days)
        threshold_iso = threshold.isoformat()
        entries = [e for e in entries if e.timestamp >= threshold_iso]
    elif since is not None:
        entries = [e for e in entries if e.timestamp >= since]

    if not entries:
        click.echo("(no dispatches in range)")
        sys.exit(0)

    # Group by task_id; aggregate engine, dispatches, tokens, cost
    by_run: dict[str, dict] = {}
    for e in entries:
        agg = by_run.setdefault(
            e.task_id,
            {
                "engines": set(),
                "dispatches": 0,
                "in_tokens": 0,
                "out_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        agg["engines"].add(e.engine)
        agg["dispatches"] += 1
        agg["in_tokens"] += e.input_tokens
        agg["out_tokens"] += e.output_tokens
        agg["cost_usd"] += e.cost_usd

    # Sort: most expensive first
    rows = sorted(by_run.items(), key=lambda kv: -kv[1]["cost_usd"])[:top]
    click.echo(
        f"{'task_id':38} {'engines':18} {'dispatches':>10} {'in':>8} {'out':>8} {'cost':>10}"
    )
    grand_total_cost = 0.0
    grand_total_in = 0
    grand_total_out = 0
    for task_id, agg in rows:
        engines_str = ",".join(sorted(agg["engines"]))[:18]
        click.echo(
            f"{task_id:38} {engines_str:18} "
            f"{agg['dispatches']:>10} "
            f"{agg['in_tokens']:>8} {agg['out_tokens']:>8} "
            f"${agg['cost_usd']:>9.6f}"
        )
        grand_total_cost += agg["cost_usd"]
        grand_total_in += agg["in_tokens"]
        grand_total_out += agg["out_tokens"]

    # Footer with sum across shown rows + full-range total
    click.echo("-" * 96)
    full_range_total = sum(a["cost_usd"] for a in by_run.values())
    click.echo(
        f"{'(top ' + str(len(rows)) + ')':38} {'':18} "
        f"{'':10} {grand_total_in:>8} {grand_total_out:>8} "
        f"${grand_total_cost:>9.6f}"
    )
    if len(by_run) > top:
        click.echo(
            f"({len(by_run) - top} more runs not shown)  full-range total: ${full_range_total:.6f}"
        )
    sys.exit(0)


@budget_group.command(name="set-cap")
@click.argument("amount_usd", type=float)
def budget_set_cap(amount_usd: float) -> None:
    """Write monthly cap to coord/dev_loop/budget_cap.json.

    W14-BUDGET-METER-PER-ENGINE 2026-05-25: preserves any existing
    per-engine caps + alert threshold; only the global cap is updated.
    """
    from harness.budget import read_caps_config, write_caps_config

    # Use the cli-module DEFAULT_CAP_PATH so tests that monkeypatch
    # ``harness.cli.DEFAULT_CAP_PATH`` continue to redirect writes.
    config = read_caps_config(cap_path=DEFAULT_CAP_PATH)
    config["monthly_cap_usd"] = float(amount_usd)
    write_caps_config(config, cap_path=DEFAULT_CAP_PATH)
    click.echo(f"monthly cap set to ${amount_usd:.2f}")
    sys.exit(0)


@budget_group.command(name="set-engine-cap")
@click.argument("engine", type=str)
@click.argument("amount_usd", type=float)
def budget_set_engine_cap(engine: str, amount_usd: float) -> None:
    """W14-BUDGET-METER-PER-ENGINE: set a per-engine monthly cap.

    Examples:
      harness budget set-engine-cap deepseek 30
      harness budget set-engine-cap mimo 15
      harness budget set-engine-cap qwen 50

    Pass 0 to remove a cap entirely (engine becomes unbounded).
    """
    from harness.budget import set_engine_cap

    set_engine_cap(engine, float(amount_usd), cap_path=DEFAULT_CAP_PATH)
    if amount_usd <= 0.0:
        click.echo(f"engine cap removed for {engine}")
    else:
        click.echo(f"engine cap for {engine} set to ${amount_usd:.2f}")
    sys.exit(0)


@budget_group.command(name="caps")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["pretty", "json"]),
    default="pretty",
    help="Output format.  pretty for terminal, json for scripts.",
)
def budget_caps(fmt: str) -> None:
    """W14-BUDGET-METER-PER-ENGINE: show per-engine spend vs cap.

    Surfaces this-month spend, configured cap, percentage used, and an
    alert indicator (>=80% by default) per engine.  An engine appears
    here if it has either a cap configured OR any spend recorded this
    month.

    Exit code 0 always (read-only command).
    """
    from harness.budget import (
        all_engines_status,
        read_caps_config,
        check_cap,
    )

    # Use the cli-module DEFAULT_CAP_PATH for monkeypatch-aware reads
    config = read_caps_config(cap_path=DEFAULT_CAP_PATH)
    rows = all_engines_status(caps_config=config)
    within, spent, global_cap = check_cap()

    if fmt == "json":
        import json as _json

        click.echo(
            _json.dumps(
                {
                    "global": {
                        "monthly_cap_usd": global_cap,
                        "spent_usd": spent,
                        "within_cap": within,
                    },
                    "alert_threshold_pct": config["alert_threshold_pct"],
                    "engines": [r.model_dump() for r in rows],
                },
                indent=2,
            )
        )
        sys.exit(0)

    # Pretty terminal output with color-coded status
    if global_cap > 0:
        global_pct = (spent / global_cap) * 100.0
        global_status = (
            click.style("OVER", fg="red", bold=True)
            if not within
            else click.style("ALERT", fg="yellow", bold=True)
            if global_pct >= config["alert_threshold_pct"]
            else click.style("OK", fg="green")
        )
        click.echo(
            f"Global cap:  ${spent:.4f} / ${global_cap:.2f} ({global_pct:.1f}%)  [{global_status}]"
        )
    else:
        click.echo(f"Global cap:  not configured  (spent so far: ${spent:.4f})")
    click.echo(f"Alert threshold: {config['alert_threshold_pct']}%")
    click.echo()
    if not rows:
        click.echo("(no per-engine caps configured, no engine spend this month)")
        sys.exit(0)
    click.echo(f"{'engine':<14} {'spent':>10} {'cap':>10} {'%used':>8}  status")
    click.echo("-" * 56)
    for r in rows:
        if r.cap_usd <= 0:
            status_disp = click.style("uncapped", fg="cyan")
            pct_disp = "  -  "
        elif not r.within_cap:
            status_disp = click.style("OVER", fg="red", bold=True)
            pct_disp = f"{r.pct_used:.1f}%"
        elif r.alert_threshold_reached:
            status_disp = click.style("ALERT", fg="yellow", bold=True)
            pct_disp = f"{r.pct_used:.1f}%"
        else:
            status_disp = click.style("OK", fg="green")
            pct_disp = f"{r.pct_used:.1f}%"
        click.echo(
            f"{r.engine:<14} ${r.spent_usd:>8.4f} ${r.cap_usd:>8.2f} {pct_disp:>8}  {status_disp}"
        )
    sys.exit(0)


@budget_group.command(name="reset")
@click.option("--force", is_flag=True)
def budget_reset(force: bool) -> None:
    """Archive ledger + start fresh."""
    if not DEFAULT_LEDGER_PATH.exists():
        click.echo("ledger already empty")
        sys.exit(0)
    if not force:
        click.echo("error: use --force to reset ledger", err=True)
        sys.exit(1)
    archive = _budget_archive_dir()
    archive.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = archive / f"budget_ledger_{suffix}.jsonl"
    DEFAULT_LEDGER_PATH.rename(dest)
    click.echo(f"ledger archived to {dest}")
    sys.exit(0)


@budget_group.command(name="export-daily")
@click.option("--date", default=None, help="UTC date YYYY-MM-DD (defaults to today).")
@click.option(
    "--target-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Override output dir (defaults to coord/cost_daily/).",
)
def budget_export_daily(date: str | None, target_dir: Path | None) -> None:
    """Append-only daily cost roll-up CSV (engine/model/tokens/$ for Excel reconciliation)."""

    out = export_daily_csv(target_dir=target_dir, date=date)
    click.echo(f"wrote {out}")


# ---------------------------------------------------------------------------
# Proxy primitive (v2/A)
# ---------------------------------------------------------------------------


@cli.group(name="proxy")
def proxy_group() -> None:
    """OpenAI-compatible HTTP proxy.  Routes /v1/chat/completions
    requests from third-party tools (litellm-based clients, ApplyPilot,
    etc.) to one of 5 upstreams: kimi-http (default), deepseek-http,
    mimo-via-claude-code, kimi-via-claude-code.  The two
    subprocess upstreams are TOS-compliant for User-Agent-gated
    providers (MiMo Token Plan, Kimi Code subscription).

    Run `harness proxy upstreams` to list all options, then
    `harness proxy start --upstream <name>` to launch the daemon on
    127.0.0.1:7879.
    """


@proxy_group.command(name="start")
@click.option("--port", default=7879, type=int)
@click.option("--host", default="127.0.0.1")
@click.option(
    "--upstream",
    default="kimi-http",
    show_default=True,
    help=(
        "Upstream selector.  Run `harness proxy upstreams` to see all "
        "options.  HTTP-direct: kimi-http (default), deepseek-http, "
        "(no direct-HTTP MiMo). TOS-compliant subprocess: mimo-via-claude-code, "
        "kimi-via-claude-code."
    ),
)
def proxy_start(port: int, host: str, upstream: str) -> None:
    """Start the proxy server in the background."""
    from harness.proxy.cli import start

    start(port=port, host=host, upstream=upstream)


@proxy_group.command(name="upstreams")
@click.option(
    "--format", "fmt", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def proxy_upstreams(fmt: str) -> None:
    """List all upstream selectors the proxy supports.

    Each upstream is a named recipe: transport (HTTP-direct vs Claude
    Code subprocess) + base URL + default model + key env var.
    """
    from harness.proxy.upstreams import list_upstreams

    upstreams = list_upstreams()
    if fmt == "json":
        import json

        out = {
            name: {
                "transport": s.transport,
                "key_env": s.key_env,
                "base_url": s.base_url,
                "default_model": s.default_model,
                "description": s.description,
                "tos_notes": s.tos_notes,
            }
            for name, s in upstreams.items()
        }
        click.echo(json.dumps(out, indent=2))
        return
    # Table format
    click.echo(f"{'name':<24} {'transport':<26} {'key env':<22} model")
    click.echo("-" * 110)
    for name, s in upstreams.items():
        click.echo(f"  {name:<22} {s.transport:<26} {s.key_env:<22} {s.default_model}")
    click.echo()
    click.echo("Subprocess upstreams are TOS-compliant for UA-gated providers.")
    click.echo(
        "Latency: HTTP ~100ms overhead; subprocess ~5-7s overhead (Claude Code boot per request)."
    )


@proxy_group.command(name="stop")
def proxy_stop() -> None:
    """Stop the background proxy server."""
    from harness.proxy.cli import stop

    stop()


@proxy_group.command(name="status")
def proxy_status() -> None:
    """Show per-key health table."""
    from harness.proxy.cli import status

    status()


@proxy_group.command(name="reset-circuit")
@click.argument("alias")
def proxy_reset_circuit(alias: str) -> None:
    """Manually reset a key's circuit breaker to CLOSED."""
    from harness.proxy.cli import reset_circuit

    reset_circuit(alias)


@proxy_group.command(name="quarantine")
@click.argument("alias")
def proxy_quarantine(alias: str) -> None:
    """Permanently open a key's circuit breaker."""
    from harness.proxy.cli import quarantine

    quarantine(alias)


@proxy_group.command(name="unquarantine")
@click.option("--alias", default=None, help="Specific key alias to unquarantine.")
@click.option("--all", "all_keys", is_flag=True, help="Clear quarantine on ALL keys.")
def proxy_unquarantine(alias: str | None, all_keys: bool) -> None:
    """Clear permanent-quarantine state set by --quarantine or AUTO-QUARANTINE-KEY."""
    from harness.proxy.cli import unquarantine

    ok, msg = unquarantine(alias=alias, all_keys=all_keys)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@proxy_group.command(name="disable-key")
@click.argument("alias")
def proxy_disable_key(alias: str) -> None:
    """Manually disable a key so the proxy won't route to it."""
    from harness.proxy.cli import disable_key

    disable_key(alias)


# ── Session ──────────────────────────────────────────────────────────────


@cli.group(name="session")
def session_group() -> None:
    """Session-handoff monitor — proactive transfer recommendation."""


@session_group.command(name="check")
def session_check() -> None:
    """Run a single health check and print the report."""
    from harness.session.monitor import check

    report = check()
    click.echo(report.model_dump_json(indent=2))
    if report.recommendation.value in ("critical", "strongly"):
        raise SystemExit(1)


@session_group.command(name="bootstrap")
@click.option("--reason", default="", help="Reason / next-action for the new session.")
def session_bootstrap(reason: str) -> None:
    """Generate the 5-section master handoff prompt."""
    from harness.session.bootstrap import generate_master_prompt

    click.echo(generate_master_prompt(reason=reason))


@session_group.command(name="ack")
def session_ack() -> None:
    """Acknowledge and remove pending handoff flag files."""
    from harness.session.monitor import ack_handoff

    ok, msg = ack_handoff()
    click.echo(msg)
    sys.exit(0 if ok else 1)


@session_group.command(name="crisis-check")
def session_crisis_check() -> None:
    """Run check and raise a Windows toast on CRITICAL."""
    from harness.session.monitor import crisis_check

    report = crisis_check()
    click.echo(report.model_dump_json(indent=2))
    if report.recommendation.value == "critical":
        raise SystemExit(1)


@session_group.command(name="arm-crisis-check")
@click.option("--cadence", default=5, help="Check cadence in minutes.")
def session_arm_crisis_check(cadence: int) -> None:
    """Register a Windows Task Scheduler entry for periodic crisis checks."""
    from harness.session.monitor import arm_crisis_check

    ok, msg = arm_crisis_check(cadence_minutes=cadence)
    click.echo(msg)
    sys.exit(0 if ok else 1)


@session_group.command(name="ok-to-stop")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Emit decision as structured JSON instead of human text.",
)
def session_ok_to_stop(json_output: bool) -> None:
    """Deterministic gate — exit 0 only if the session may legitimately stop now.

    The autonomous-loop directive
    (`feedback_full_automation_until_wave_plan_empty`) says: do NOT stop
    until session-handoff is STRONGLY/CRITICAL or operator explicitly
    redirects.  This verb encodes that rule programmatically so the
    agent (or a wrapper script) can check before any 'stopping' reply.

    Exit codes:
      0 — stopping is appropriate (reason printed)
      1 — stopping is premature; keep working (reason printed)

    --json emits {ok_to_stop, reason, ...inputs} for programmatic consumers
    (dashboard, chat observer, wrapper scripts).
    """
    from harness.session.stop_check import ok_to_stop_with_inputs

    ok, reason, inputs = ok_to_stop_with_inputs()
    if json_output:
        import json as _json

        payload = {"ok_to_stop": ok, "reason": reason, **inputs}
        click.echo(_json.dumps(payload))
    else:
        click.echo(("ok-to-stop: " if ok else "NOT-YET: ") + reason)
    sys.exit(0 if ok else 1)
