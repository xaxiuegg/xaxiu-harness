<!-- persona=A2-adapter-onboarding status=OK (11480ms) -->

# A2-adapter-onboarding

**1. Headline verdict**  
YES-IF — the adapter format and NL→YAML generation are promising for agent onboarding, but several friction points must be resolved before the path is frictionless.

**2. Strongest evidence FOR**  
- The `adapter from-description` verb directly mirrors how an agent works: read a one‑paragraph project description and produce a structured YAML adapter. This replaces manual schema study and reduces the designer’s cognitive load to one tool call.  
- Adapter YAML is a single declarative file covering engine routing, fallback chains, status fields, and provider config. Agents excel at parsing and generating such structured documents.  
- The included sample adapters (`spec/`) and the CLI help give agents enough context to produce correct output without reading the full source, matching the “copy‑paste‑and‑adjust” pattern they favour.

**3. Strongest evidence AGAINST**  
- The YAML schema is *not* self‑explanatory from a quick read—nested keys like `provided_rules`, `inter_data_dependencies`, and `pass_condition` require domain knowledge that an agent may not possess without scanning the full adapter loader source or error messages.  
- NL→YAML generation often produces structurally valid but semantically weak adapters (e.g., missing required fallback chains, over‑generalised routing). The human designer can iterate; an agent that blindly trusts the output will fail silently until runtime.  
- The validation CLI (`adapter validate`) exists but its messages are designed for human eyes, not agentic parsing—there is no machine‑readable error JSON or structured feedback loop for automatic correction.

**4. The 3 most important W11 changes**  
1. **Add `adapter validate --json`** that outputs structured validation errors (reason, path, severity). This lets agents auto‑correct adapters in a loop without interpreting free‑text messages.  
2. **Ship a “minimum viable adapter” template** with only the required keys and comments. Current samples show too many optional fields; an agent copying those may over‑engineer or miss critical links.  
3. **Provide a `adapter bootstrap` command** that runs `from-description`, validates, shows a diff, and optionally writes the adapter—all in one agent‑callable workflow. Combine with a hard pre‑run test that verifies the adapter works against the local engine pool.

**5. Single-sentence recommendation**  
Pivot to dual‑target by W11: optimise the adapter pipeline for agent automation (structured feedback, minimal template, bootstrap command) while keeping the human‑friendly NL path as a fallback.
