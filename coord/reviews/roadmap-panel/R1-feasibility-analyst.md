<!-- persona=R1-feasibility-analyst status=OK (27087ms) -->

# R1-feasibility-analyst

1. **Headline verdict**: YES-IF – the core dispatch, circuit-breaker, and cost-ledger architecture survives a chat-tier rewrite; the CLI and YAML surface are the only blockers, not the engine.

2. **Wave-count estimate**: 5 waves p50, 3–8 p90 (W11–W15/18). Building a conversational wrapper (Slack bot, local web chat, or embedded REPL) plus fixing the first-run gauntlet and adding natural-language intent parsing requires ~2 waves for scaffolding, 1 wave for DPAPI/Credential wizard, 1 wave for stateful session/idempotency, and 1 wave for polish + testing. The existing CLI subcommands become internal API endpoints.

3. **The 3 most load-bearing decisions in W11**:
   - **Define the conversational contract**: pick a single target interface (e.g., localhost web chat using FastAPI + WebSocket) and commit to it. This kills the CLI as the primary UX – all new features must be exposed via that interface first, CLI second.
   - **Rewrite `harness preflight` as a guided multi-step wizard** that outputs plain-language instructions, not PASS/FAIL verdicts. The current git-clean blocker must be replaced with an interactive “stash changes? (y/n)” or auto-stash with undo.
   - **Replace YAML config files with a single JSON blob persisted behind the conversation** (e.g., `profile.json` managed by the chat agent). Editing YAML is a non-negotiable showstopper for a ChatGPT-tier user; the chat interface must read/write config via natural language inference.

4. **The one thing to CUT or HIDE**: **All `harness status list` line-oriented output and `--recent` formatting**. A chat-tier user never wants to see a terminal table; that data must be surfaced as a single sentence (“Your latest run from 3h ago passed – cost $0.04, 5/5 tests green.”) or a minimal UI card. Hide the entire `harness status` subcommand behind a `/status` slash command that returns markdown.

5. **The one risk most likely to derail the trajectory**: **Ambiguity of intent parsing in a non-DSL conversation**. The existing dispatch layer expects structured commands (engine, model, fallback policy). If the chat interface misinterprets “run the audit again but cheaper” as “rerun with engine=gemini” instead of “rerun with max-cost-budget=$0.10”, the user gets unpredictable results and loses trust. Without a strict intent schema (e.g., slot-filling with confirmation), the system becomes worse than CLI.

6. **Single-sentence recommendation**: Go – but immediately pivot the W11+ roadmap from “polish CLI” to “build a conversational agent that wraps the existing engine layer, and treat the CLI as a debugging backdoor only.”
