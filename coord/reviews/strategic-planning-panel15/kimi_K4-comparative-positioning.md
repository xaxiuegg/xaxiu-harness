### 1. Lens-specific findings

* **The context-frugal SDK is the only genuine moat versus Claude Code CLI, Aider, Cursor, and OpenDevin.**  
  > "The default mode is context-frugal: result.text is None and only result.summary is populated (~300 chars)... This is the load-bearing design choice — your agent context grows ~36 tokens per dispatch instead of ~1500." (AGENT_QUICKSTART.md)  
  Competitors burn full context on every turn and have no cross-engine fallback chain that preserves operator context this aggressively.

* **`harness review` is the only shipped feature with no competitor equivalent; it is the concrete value prop.**  
  > "Rewrite README around the harness review use case — the most concrete value-prop we have." (master-audit-2026-05-25.md)  
  Neither Claude Code, Aider, nor OpenDevin offer a single-command, multi-engine cross-check of arbitrary PDFs/MDs with synthesized Markdown output.

* **The coord pipeline recreates Aider’s architect/editor loop and OpenDevin’s task runner without their git integration or sandboxing, adding bloat with no comparative advantage.**  
  > "The harness's job is to protect the operator's time, not to consume it." (INTERNAL_OPERATOR_RUNBOOK.md)  
  The `coord plan/run/integrate` verbs are hidden in `--advanced` for a reason: they duplicate what agentic IDEs already do better.

* **The dashboard is localhost-only technical debt that competes with nothing; it should be frozen, not deferred.**  
  > "W11-DASHBOARD-AS-DEFAULT-SURFACE... DEFERRED to W15+ humans-inherit track." (STATUS.csv)  
  Cursor owns the IDE surface; Claude Code owns the terminal-rich UI. A localhost cost widget is not a differentiator.

* **The observer + watchdog is unique maintenance infrastructure that no competitor offers.**  
  > "The 24h autonomous test is the load-bearing claim that hasn't resolved yet." (master-audit-2026-05-25.md)  
  No other dev-agent tool self-monitors its own health via cron/Task Scheduler with L5 escalation; this is real internal-tool differentiation.

* **Wave 15 plugin architecture is over-engineering