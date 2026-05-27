# deepseek-via-claude

**latency**: 22.0s   **tokens_in**: 834   **tokens_out**: 1085   **cost**: $0.0571
**winning_alias**: k1   **attempts**: 1

---

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