# Packet: Wave B/2 — boundary tests for engines/guards.py

## Mission

Add boundary tests for `src/harness/engines/guards.py` covering every guard detector (packet-trap, refusal, empty, anchor-fuzzy). Push coverage of that module from current 39% to >70%.

## Scope (disjoint from Wave B/1)

In-scope NEW file: `tests/test_engines_guards_boundary.py` only.

Out-of-scope:
- `tests/test_engines_concrete_boundary.py` (sibling packet, Wave B/1)
- Any modification to `src/harness/engines/guards.py` itself
- Any existing test files

## Required tests (per detector)

Read `src/harness/engines/guards.py` to enumerate the detector functions. For each one:

1. **Positive case** — feed an example bad output that the detector should flag → assert it flags.
2. **Negative case** — feed clean output that the detector should NOT flag → assert it passes.
3. **Edge cases** — empty string, whitespace-only, very long output (10KB+), Unicode, partial match boundaries.

Specific test examples to include:

- **PacketTrap (DSML tool-call attempt)** — based on memory `feedback_deepseek_v4_no_tools_packet`, DeepSeek v4-flash sometimes emits raw DSML like `<function_calls>\n<invoke name="Edit"\n<parameter name="file_path">...`. Feed a sample with this pattern; guard MUST flag it. Negative: feed prose with mention of `<function_calls>` inside a code-fenced markdown block (literally documenting it, not invoking) → should NOT flag.
- **Refusal** — feed responses like "I can't help with that", "I cannot assist", "As an AI..." → guard flags. Negative: feed normal responses → does not flag.
- **Empty** — feed empty string, whitespace-only, single newline → guard flags. Negative: short but content-bearing response (e.g. "OK.") → does not flag.
- **Anchor-fuzzy** — if the guard checks for normalized vs verbatim quote matching (per `feedback_engine_anchor_accuracy`), feed examples with smart-quotes, indent drift, etc. that should be flagged for further review.

## Acceptance criteria

1. `python -m pytest tests/ -q` shows ≥89 + new tests, all green.
2. `python -m pytest tests/ --cov=src/harness/engines/guards --cov-report=term-missing | tail -10` shows `engines/guards.py` coverage > 70%.
3. No modifications to any file outside `tests/test_engines_guards_boundary.py`.
4. Single commit at the end: `test(engines/guards): boundary tests (Wave B/2)`.

## Reference

- `src/harness/engines/guards.py` — read first to enumerate detector functions and understand their signatures
- Memory `feedback_deepseek_v4_no_tools_packet` — example bad DSML output (informs PacketTrap test)
- Memory `feedback_engine_anchor_accuracy` — anchor drift behavior (informs anchor-fuzzy test if such a guard exists)

## Output format

Single new file at `tests/test_engines_guards_boundary.py`. No modifications elsewhere.
