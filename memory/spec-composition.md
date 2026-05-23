# Spec composition — how to write a harness spec

When the orchestrator (you, if you're reading this as an engine
prompt) needs to compose a spec for `coord run`, follow this template.

## Template

```markdown
# <SPEC-ID-IN-CAPS>: <one-line goal>

**Purpose**: <2-3 sentences on why this spec exists>

## Goal

<3-6 sentences describing what should change.  Be specific about
file paths and intended edit patterns.>

## Acceptance

1. <Bulleted assertion that can be verified mechanically>
2. <File X contains text Y / does NOT contain text Z>
3. <`python -m py_compile <file>` passes if Python>
4. <existing tests still pass>

## Why this spec exists

<1-2 paragraphs: what triggered this, what's the broader context,
which STATUS.csv row does it advance>
```

## Quality bar

- **Acceptance must be machine-checkable**: "looks better" or "is
  cleaner" are not valid.  Prefer concrete file-exists / file-contains
  / regex-matches / exit-code-zero.
- **Read-set is implicit**: planner extracts read_set from any file
  path mentioned in the Goal / Acceptance sections.  Mention every
  file you want the worker to see.
- **One worker per file conflict**: if multiple workers would edit
  the same file, declare `depends_on` between them or unify into one
  worker.

## Don'ts

- Don't mention prose like "make it clearer" — be specific.
- Don't ask for behaviour changes without acceptance criteria.
- Don't reference SHA/commit/run-id placeholders the engine cannot
  resolve.  If your spec needs prior context, attach it as read-set
  files.
- Don't exceed 200 lines per spec.  Long specs are a planner
  smell — decompose into multi-worker plans.

## Examples from real pilots

- `spec/samples/pilot-G1-script-docstring.md` — single-step Python
  comment append.  Crisp acceptance, single file write_set.
- `spec/samples/pilot-G3-multiworker-independent.md` — two workers
  editing different docs files.  No deps; acceptance lists per-worker
  files_modified.
- `spec/samples/pilot-readme-pilot-note.md` — append section to
  existing markdown.  Append-at-end pattern.

## What the planner does with this

The harness's `coord plan` runs your spec through a planner engine
(usually `swarm/claude` for in-session, but any engine works).  The
planner reads your markdown, extracts the goal + acceptance, and
emits a `WavePlan` JSON with:
- One or more workers
- `target_files` per step (extracted from your spec)
- `read_set` (all files mentioned)
- `write_set` (files in target_files)
- `kind` ('edit' for existing files, 'create' for new files)

If your spec is poorly composed (ambiguous, missing read_set hints,
no machine-checkable acceptance), the planner will guess — often
wrong.  Spend a few extra minutes on the spec; you save many on
debugging.
