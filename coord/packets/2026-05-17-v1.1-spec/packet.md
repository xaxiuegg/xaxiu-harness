# Packet: xaxiu-harness v1.1 Operator Experience Layer

## Mission
Produce a supplemental spec at `D:/Projects/xaxiu-harness/spec/v1.1-operator-experience.md` that adds the missing operator-experience layer to the v1 architecture spec. The v1 doc stays as-is; v1.1 sits on top.

## Context
The v1 spec (provided as context-file) defines a solid technical skeleton but treats "non-technical operator" as "make the YAML readable" rather than "operator never touches YAML." The operator is genuinely non-technical — can edit YAML in a pinch but should be configuring via GUI / templates / natural language by default. YAML stays canonical (what the harness reads); operator-facing surfaces (forms, NL prompts, templates) write to YAML under the hood.

## Critical constraints (reiterated)
1. Operator cannot author Python/shell from scratch — but CAN edit YAML/run commands/manage Task Scheduler
2. Default UX path must NEVER require operator to edit YAML directly
3. YAML stays as the canonical config format; operator-facing surfaces write to YAML invisibly
4. Power-user fallback ("Edit YAML directly" button) exists for rare cases but is never the primary path

## Required output sections — all 6, in order

### 1. Operator interaction surface map
Catalog every UI moment the operator sees from install through daily use: install (double-click .exe → wizard), first run (API key entry, project picker, dashboard auto-open), daily (dashboard at `localhost:7878`, engine tiles, event stream, priority toggles), add project (template picker → form → done, no terminal), edit project config (form-based editor writing YAML invisibly), power-user fallback (Edit YAML Directly button). For each moment: what operator sees / what operator does / what harness does under the hood.

### 2. Template library
The v1 must ship with ≥5 starter templates. Each = complete adapter YAML + one-paragraph operator-facing description:
1. `warehouse-style` — observer + STATUS.csv + drift checks (parity with current warehouse setup)
2. `generic-coding` — Kimi-first for routine code, DeepSeek for large files, no observer
3. `writing-content` — Kimi for drafts, DeepSeek for editing, markdown TOC status
4. `research-comparison` — burst-route to multiple engines for A/B testing, comparison view
5. `solo-dev` — minimal config, single engine, just routing + history

Operator picks at "new project" time; templates are starting points they edit via forms.

### 3. Visual config builder (dashboard surface)
Spec the form layouts in the dashboard for editing adapter YAML without writing YAML: routing rules (add rule modal: condition dropdown / action dropdown / reason text), status tracking (backend dropdown + config form per choice), observer (toggle + cadence slider + retro time picker + flag pattern multi-add), scheduled tasks (cron builder with human-readable "Every 30 min" → cron under the hood). Every form writes to the project's YAML; the YAML stays canonical, the form is the UX.

### 4. Natural-language → YAML translator
Operator types into the dashboard: "Set up my book-writing project. Drafts to Kimi, polishing to DeepSeek, status as a markdown file." Harness uses a built-in LLM call (Kimi-api, low-cost) to translate into valid adapter YAML, shows it in the visual builder, operator tweaks via forms, saves. Spec: prompt template, validation pipeline (must pass Pydantic schema before save), error-handling UX when NL translation produces invalid config.

### 5. Windows installer (Inno Setup) full flow
1. Double-click `xaxiu-harness-setup-v1.0.exe` → Inno Setup wizard (install location, Start Menu, Task Scheduler permission)
2. Bundled Python runtime (no system Python required)
3. Post-install launches first-run wizard (PyWebview window): welcome → API key entry form (reuses env vars if detected, else prompts) → optional xaxiu-swarm config import if found → "Set up first project?" template picker → "Open dashboard?" launches browser to localhost:7878
4. Quiet thereafter; Task Scheduler runs everything
5. Also spec: uninstaller flow, settings preservation across upgrades, upgrade installer behavior

### 6. Satisfactory-inspired dashboard aesthetic
Concrete CSS/visual direction: dark steel base (#0F1318) with subtle blueprint grid background; amber/cyan accents (#FFA94D / #4DD0E1) for engine status; engine tiles pulse subtle color with current load (mood-ring); pipe/conveyor flow lines animate between project → engine → dispatch when in flight; monospace numerics (JetBrains Mono); status pills (●/○/✓/✗/⚠/⟲) with industrial-readout feel; decision archaeology panel for clicked dispatches (packet, fallback chain, patch, result, cost); failures flash red and recovery animates green (small dopamine, not noise); loops shown as orbit-strips with sparkline history. Include 2-3 ASCII layout sketches matching the v1 dashboard mock style.

## Output format
Single markdown doc. Target 250–450 lines. Use tables for surface maps, YAML code blocks for templates, form-layout mocks for builder, ASCII for dashboard sketches. No "executive summary" — sections themselves are the spec. Reader is an implementer (Kimi or DeepSeek) who will dispatch the operator-experience layer in subsequent packets.

## Reference
- v1 architecture spec attached as context-file — build ON it, do not re-derive
- Satisfactory aesthetic precedent: dark industrial, real-time feedback, decision archaeology, mood-ring status, holographic-industrial language
