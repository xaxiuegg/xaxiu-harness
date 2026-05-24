### Verdict
`NEEDS-WORK` — the Python SDK dispatch path is proven live (E2E against Kimi/DeepSeek/MiMo), but the CLI onboarding path advertised in AGENT_QUICKSTART.md is broken on Windows cp1252: `harness --help`, `harness preflight`, and `harness agent init` all crash with `UnicodeEncodeError`. A Windows operator following the doc literally cannot discover commands or run the readiness gate.

### Confidence
0.72

### Top-3 concrete recommendations

1. **Replace all non-ASCII glyphs in CLI output with ASCII-safe fallbacks on Windows**  
   AGENT_QUICKSTART.md markets the CLI as the primary surface (`harness today`, `harness preflight`, `harness agent init`), yet evidence shows `→` (preflight fix hint), `α` (help text), and `✓` (agent init summary) all crash the cp1252 console.  
   *Grounded in:* evidence `04_preflight.txt` (`\u2192`), `06_harness_help.txt` (`\u03b1`), `15_agent_init_dry.txt` (`\u2713`).  
   *Effort:* S

2. **Correct AGENT_QUICKSTART.md install instructions to match the tested execution path**  
   The doc says `pip install -e .`, but every internal test invocation in the evidence uses `PYTHONPATH=src python -m pytest` and `python -m harness` (no setup.py/pyproject.toml visible). If `pip install -e .` is untested, it is likely the operator’s first failure.  
   *Grounded in:* evidence `16_wave_11_closeout.md` (test command `PYTHONPATH=src python -m pytest tests/ -q`), `17_AGENT_QUICKSTART.md` (claims `pip install -e .`).  
   *Effort:* S

3. **Add a Windows cp1252 smoke gate to CI before claiming agent-ready**  
   The existing Windows matrix (evidence 08) is not catching console-encoding crashes because they only surface when Click writes to a non-UTF-8 stdout. A single CI step running `python -m harness --help` and `harness preflight` on a vanilla Windows cmd.exe would have blocked Wave 11 ship.  
   *Grounded in:* evidence `06_harness_help.txt` (help crash), `04_preflight.txt` (preflight crash).  
   *Effort:* M

### Operator vote
`WAIT-FOR-WAVE-12` — the agentic Python import path works, but the operator CLI onboarding path is non-functional on Windows. These are fixable in a few hours, yet they are absolute blockers for a non-technical operator cloning today.

### Single quote from evidence
> `UnicodeEncodeError: 'charmap' codec can't encode character '\u03b1' in position 2956: character maps to <undefined>`  
> — evidence `06_harness_help.txt`