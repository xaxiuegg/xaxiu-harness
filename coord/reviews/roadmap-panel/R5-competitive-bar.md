<!-- persona=R5-competitive-bar status=OK (16763ms) -->

# R5-competitive-bar

## Competitive-Landscape Review

### 1. Headline Verdict
**NEEDS-PIVOT** — as a CLI‑only tool with YAML config, the harness cannot reach 7/10 for a ChatGPT‑tier user without a fundamental shift to a GUI‑first experience.

### 2. Wave-Count Estimate
8 waves P50, 5–12 P90. The first 3 waves must be spent exclusively on replacing the CLI surface with a default web dashboard + one‑click installer, or the gap only widens.

### 3. Three Load-Bearing Decisions (W11)

1. **Default to the FastAPI dashboard on `harness start`**, not the CLI. Make the browser the primary interface; relegate CLI to an opt‑in `--cli` flag. This matches every competitor’s first‑screen layout (chat window, not a terminal).

2. **Ship a single‑file `.exe` installer that bundles Python + dependencies**, handles DPAPI enrollment, and lands the user on the dashboard within 30 seconds. Current “git clone + pip install” is a blocker that rival products (LM Studio, Ollama desktop) solved years ago.

3. **Replace the YAML settings panel with a GUI modal** (model selection, API key input, engine fallback order, temperature). Hide every YAML file behind “Advanced Settings”. Non‑technical users will never touch YAML.

### 4. Cut or Hide
**Harness Coordination (coord) – all 13 subcommands.** A chat‑tier user does not want a multi‑agent worktree pipeline. They want a single text box and a send button. Move `coord` to a hidden `--advanced` namespace or deprecate it entirely.

### 5. One Risk Most Likely to Derail Trajectory
**Continuing to build CLI depth (more verbs, flags, YAML knobs) under the illusion that “operator profiles” can paper over the absence of a GUI.** Every wave spent on CLI features directly widens the competitive chasm with ChatGPT Desktop / LM Studio / Open‑WebUI, which already deliver a zero‑config chat experience.

### 6. Single-Sentence Recommendation
Pivot now: freeze all CLI‑only features, build a one‑click installer + default web UI in W11–W13, and treat the current CLI as a power‑user add‑on; otherwise the project will never serve its intended non‑technical audience.
