# `memory/` — engine-agnostic operator knowledge

This directory holds operator-curated knowledge that **any engine** in
the harness reads when dispatched.  Replaces the Claude-specific
`~/.claude/projects/*/memory/` which only Claude saw.

## Purpose

When a worker subprocess builds a dispatch packet, it auto-includes
all `memory/*.md` files so the engine has the operator's standing
decisions, conventions, and known engine quirks before composing
its output.

This is the harness's mechanism for **engine substitutability**: any
of MiMo / DeepSeek / Kimi-CLI / Claude can step into the orchestrator
or worker role and produce operator-aligned output because they all
read the same memory.

## Conventions

- One topic per file, kebab-case name
- 50-300 lines; brief enough that all files combined fit a typical
  packet budget (~8KB total recommended)
- Markdown with `## Goal`, `## Don'ts`, `## Examples` sections where
  applicable
- Date-stamped at top so engines can detect stale guidance

## Files (alphabetical)

Listed by `harness memory list`.  Engines can `harness memory show
<name>` for individual reads, or just let the worker prompt auto-include
them.

## What goes here vs elsewhere

| Knowledge type | Location |
|----------------|----------|
| Operator standing decisions | `memory/*.md` (this dir) — **engine-agnostic** |
| Coding conventions for this repo | `memory/*.md` |
| Engine quirks / reliability findings | `memory/*.md` |
| Task tracker | `coord/STATUS.csv` (not memory; separate purpose) |
| Synthesis reports | `coord/coverage/*.md` (per-investigation; not memory) |
| Claude-specific session-state | `~/.claude/projects/*/memory/` (personal, not committed) |
