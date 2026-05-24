### Verdict
NEEDS-WORK

### Confidence
0.9

### Top-3 concrete recommendations

1. **Sanitize all CLI output to ASCII-only**: Replace Unicode glyphs (`✓`, `→`, `—`, `α`) with ASCII equivalents across `cli.py`, `l5_escalation.py`, `preflight.py`, and `agent/__init__.py` to eliminate cp1252 encode errors on default Windows consoles.
   - **Grounding**: evidence 01 line 2 (em-dash in `harness today`), evidence 04 line 18 (arrow `\u2192` in preflight remediation), evidence 06 line 24 (alpha `\u03b1` in help text), evidence 07 line 5 (em-dash in L5 banner), evidence 08 line 15 (em-dash in advanced list), evidence 15 line 24 (checkmark `\u2713` in agent init).
   - **Effort**: M

2. **Add a non-ASCII lint gate for CLI strings**: Introduce a CI test that greps for non-ASCII characters inside `click.echo` argument strings/f-strings in `src/harness/cli.py` and related CLI modules, failing the build on regressions.
   - **Grounding**: evidence 04 line 16 (crash site is `click.echo`), evidence 06 line 20 (crash site is `click.echo`), evidence 15 line 22 (crash site is `click.echo`).
   - **Effort**: S

3. **Bootstrap Windows console to UTF-8 at startup**: Add a startup check in `__main__.py