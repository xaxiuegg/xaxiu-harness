# kimi-via-claude

**latency**: 110.7s   **tokens_in**: 675   **tokens_out**: 4095   **cost**: $0.1080
**winning_alias**: k1   **attempts**: 1

---

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