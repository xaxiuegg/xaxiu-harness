<!-- persona=U4-error-recovery status=OK (25096ms) -->

# U4-error-recovery

## 1. Top 3 Changes (Leverage Ranking)

1. **Contextual error-to-recovery mapping**: Replace `[X] git_clean` with: `"[!] Uncommitted files: 'prompt.md', 'output.csv'. Fix: Run 'harness recover git' (stash & commit) or 'harness recover git --drop' (discard changes)."` One command, plain language, immediate action.

2. **A single `harness recover` wizard**: On any failure, the CLI prompts: `"Something needs fixing. What happened? [1] Engine died [2] Files are messy [3] Secret missing [4] I don't know."` Selecting "I don't know" runs a full diagnostic and outputs a numbered fix plan. No command memorization.

3. **Visual recovery progress**: After a fix, show a green bar: `"RECOVERY COMPLETE [██████████] 4/4 checks passed: Engine 'DeepSeek' reconnected, untracked files committed, secret 'OPENAI_KEY' detected, observer restarted."` The operator sees success, not just absence of errors.

## 2. Wave 11 Candidate Row

**W11-RECOVERY-WIZARD-INTERACTIVE**
Acceptance criteria: When `harness preflight` or any dispatch fails, the operator can type `harness recover` and enter an interactive TUI (text-based UI) that lists failures as simple questions, offers 1-2 fix options per item (with `--dry-run` previews), and executes chosen fixes sequentially with progress bars. Success = operator resolves 80% of common failures without leaving the wizard or reading documentation.

## 3. Feature to KILL/HIDE

**Kill `engines-heal` as a standalone verb.** It's a technical deep-dive command that overlaps with recovery flows. Hide it behind `harness engines --advanced heal` or merge its logic into the `recover` wizard's "Engine died" path. The operator shouldn't need to know the difference between `heal` and `reset` and `quarantine`.

## 4. Minimum Viable First-Run Path

1. `cd D:\xaxiu-harness-standalone`
2. `harness setup` (single command: checks Python, creates folder, seeds sample YAML, shows "✓ Ready").
3. `harness authenticate` (wizard: paste one API key, tests connection).
4. `harness day-start` (wraps `preflight` + `today`; output is a one-paragraph status with a single "✓ All clear" or "⚠ 1 issue—run `harness fix`").

Total: 4 commands, no decisions, no doc-reading.

## 5. Trust Seam

**The "wall of green" confirmation.** After any recovery or setup, display a 4-line ASCII dashboard:
```
ENGINES [✓ DeepSeek] [✓ Kimi]
FILES   [✓ 0 uncommitted]
SECRETS [✓ 3/3 detected]
OBSERVER[✓ Running]
```
This is the only trust signal that matters: a binary, visual summary of system health that matches their mental model of "everything is working." No log parsing required.
