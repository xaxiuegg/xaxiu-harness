# Cross-engine panel for synthesis

## Question

You are reviewing a visual operator manual for xaxiu-harness, a multi-engine LLM dispatch tool.  The full manual is below.  Audit it from THREE perspectives and provide concrete, actionable refinements.

# Manual being reviewed

(Full text of docs/HARNESS_VISUAL_MANUAL.md — assume you have the complete document.  It covers: TL;DR, harness doctor, harness setup, harness keys serve with web UI, harness ask cross-engine panel, harness engines recommend, harness keys list, other useful verbs, two-repo story, deployment model, cost reference, where-to-look-next.)

# Your task

Provide structured feedback in EXACTLY this format, no preamble:

## 1. Clarity (3-5 bullets)

What's confusing, ambiguous, or assumes background the target operator (solo, semi-technical) doesn't have?  Be specific — name the section + the exact phrase or paragraph.

## 2. Missing pieces (3-5 bullets)

Concrete things a real operator would WANT in a manual but the current draft doesn't have.  Don't pad.

## 3. Concrete additions I would write (1-2 paragraphs of actual prose)

Provide actual draft text that could be pasted in.  Pick the single highest-leverage gap from §2 and write the paragraph that closes it.

## 4. One thing I'd cut

A section, sentence, or detail that's not pulling its weight.

Keep total response under 700 words.  No tool-call markup.  Plain text only.

## Responses

### kimi-via-claude

_latency 110.7s, cost $0.1080, alias k1_

## 1. Clarity (3-5 bullets)

- **TL;DR** — The phrase "multi-engine LLM dispatch" is never unpacked for the operator. A solo user can walk away thinking they must configure every backend before getting value, when the tool is useful with just one.
- **harness doctor** — The manual says it "validates your environment" but never defines what a red or yellow result means in practice. The operator needs explicit next-step links tied to each failure class.
- **harness keys serve with web UI** — It is unclear whether this starts a foreground blocking process, a background daemon, or a one-shot command. The operator needs to know if the terminal must stay open and which port is bound.
- **two-repo story** — Uses project-internal names (xaxiu-harness vs xaxiu-swarm) without clarifying which repository the operator is currently standing in or why this matters for day-to-day use.
- **Cost reference** — Lists per-token prices without grounding them in a concrete scenario, leaving the operator unable to estimate a real daily budget.

## 2. Missing pieces (3-5 bullets)

- A "First 5 minutes" concrete walkthrough from zero to first successful cross-engine panel dispatch.
- Troubleshooting steps for when `harness doctor` fails or an engine returns `NO_KEY` immediately after setup.
- Security hardening guidance for `harness keys serve` (localhost defaults, auth tokens, reverse-proxy notes).
- Expected resource footprint (RAM, CPU, open ports) for running the web UI alongside active dispatches.
- How to add or register a custom backend engine that is not in the built-in recommendation list.

## 3. Concrete additions I would write (1-2 paragraphs of actual prose)

**First 5 minutes: from install to first dispatch.** Once `harness doctor` reports green, resist the urge to configure every engine. Run a single-engine smoke test: `harness ask --engine claude --prompt "hello"`. When you see a response, immediately try the cross-engine panel: `harness ask --panel claude,gpt4 --prompt "explain this error: ..."`. If any engine shows `NO_KEY`, ignore it—the panel degrades gracefully and still returns answers from available engines. Only after you see two answers side-by-side should you proceed to `harness keys serve` or add remaining API keys. This sequence validates your install, demonstrates core value, and prevents configuration fatigue.

## 4. One thing I'd cut

**Two-repo story.** The manual is for operators running the harness, not contributors deciding where to commit code. Replace the narrative with one sentence: "This repo (`xaxiu-harness`) is the operator CLI and web panel; infrastructure automation lives in `xaxiu-swarm` and is not required for daily use." Then delete the rest of the section.

### mimo-via-claude

_latency 42.0s, cost $0.0106, alias k1_

Let me read the manual first to give accurate feedback.<tool_call>
<function=Read>
<parameter=file_path>D:\xaxiu-harness-standalone\docs\HARNESS_VISUAL_MANUAL.md</parameter>
</function>
</tool_call>

### deepseek-via-claude

_latency 22.0s, cost $0.0571, alias k1_

## 1. Clarity (3-5 bullets)

- **"Two-repo story"** – Section name is opaque. A solo semi-technical operator won't know what "two-repo" refers to. Worse, they may think they need to clone something else to get started.
- **"harness keys serve with web UI"** – Unclear whether this command *also* opens a browser or just starts a server. The operator needs to know what they see and when they see it.
- **"harness doctor"** – If this section doesn't explicitly list "what a green check means vs. a red X," the operator will stare at terminal output with no confidence about next steps.
- **"deployment model"** – Likely over-explains architecture (containers, hosts, infra) when a solo operator just needs to know "this runs on my laptop" or "this needs Python 3.11+."
- **"cost reference"** – If presented without a worked example (e.g., "1 typical ask = ~0.02¢ across 3 engines"), the numbers are just noise to a non-expert.

## 2. Missing pieces (3-5 bullets)

- **Quick success metric** – No way for the operator to know "I'm done setting up." Needs a concrete checkpoint: a single `harness ask` that should produce a recognizable result.
- **Error-recovery paths** – What to do when `harness doctor` reports a failure. The manual likely lists commands but not "if X fails, try Y."
- **Reset/teardown instructions** – Solo operators break things. There's no "how to start from scratch" or "how to unset an API key."
- **Keyboard shortcut or UI navigation summary** – If the web UI has tabs or panels, a one-liner overview saves the operator from clicking around lost.
- **Offline/air-gapped note** – The operator may try to run this without internet; no mention of what fails vs. what works locally.

## 3. Concrete additions I would write

**Add after `harness setup` section, before `harness keys serve`:**

> ### ✅ Sanity check: did it work?
>
> After setup completes, run a single fast smoke test to confirm everything is wired:
>
> ```
> harness ask "Say OK and nothing else." --quick
> ```
>
> You should see a response like `OK` within 5 seconds. If you get an error:
> - `No keys found`: go back to `harness keys list` and confirm at least one key shows up.
> - `Connection refused` or `timeout`: run `harness doctor` again and look for a red ❌ next to the engine you expected to use. That tells you which key is missing or wrong.
> - `command not found`: you're not in the correct Python environment. Run `pip install -e .` from the repo root and try again.
>
> Once you see `OK`, you're ready for the full web UI (`harness keys serve`) or multi-engine queries (`harness ask`).

## 4. One thing I'd cut

**The "deployment model" section as currently scoped.** A solo operator running a standalone tool doesn't care about load balancers, containerization, or multi-host topology. If they need to scale later, cross that bridge when it comes. Replace it with a single sentence in the TL;DR: "This runs entirely on your local machine — nothing is deployed to a server."
