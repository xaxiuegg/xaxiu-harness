### 1. Lens-specific findings

**1. I only remember 4 CLI verbs, and the runbook pretends I know 38.**
A year from now my actual daily loop is `harness today`, `harness review`, `harness cost-today`, and `harness preflight`. The bloat audit admits the truth: there are **"30+ CLI verbs + their flags"** and **"Bloat risk: MEDIUM and growing."** I haven't run `harness coord` or touched `harness advanced list` in nine months. Those verbs are archaeological layers I ignore.

**2. `harness review` is the only feature that ever paid rent; everything else is operational noise.**
The master audit nailed it: **"Rewrite README around the `harness review` use case — the most concrete value-prop we have."** A year later, roughly 90% of my dispatches are `harness review <client-file.pdf>`. Waves, STATUS.csv grooming, and panel dispatches are just the price I pay to keep the lights on, not value I extract.

**3. The context-frugal return mode is why I still have a context window.**
The AGENT_QUICKSTART states: **"your agent context grows ~36 tokens per dispatch instead of ~1500."** That auto-default was genius. I stopped thinking about token limits entirely; the harness became invisible infrastructure. When I occasionally bypass it with `.full()`, it's a deliberate choice, not an accident.

**4. The runbook lied to me about `harness secrets rotate kimi`, and I believed it.**
The bloat audit caught this exactly: **"Future-as-present in docs — runbook describes `harness secrets rotate kimi` (doesn't exist)."** Six months in I had a leaked key, tried the command, got `command not found`, and had to fall back to manual `.env` editing while a client was waiting. Future-as-present documentation is not a nit; it's a live outage that burns trust.

**5. Default `max_tokens` burned my DeepSeek budget because auto-pick wasn't shipped.**
The STATUS.csv row W12-B-MAX-TOKENS-DEFAULT-RAISE notes: **"paid engines (DeepSeek) at 8k output still costs <$0.01/call."** One Tuesday I reviewed a 40-page PDF and forgot to cap DeepSeek; it generated 6k tokens. The cost was pennies, but the shock broke my trust for a week. The bloat audit's auto-default rule—**"visible + overridable + auditable"**—would have prevented this. I got none of those.

**6. The harness flipped from "project I manage" to "plumbing I depend on."**
The Horizon C plan says: **"Build an internal tool that the operator can DEPEND ON."** A year later I don't think about waves or commits. But that dependency is brittle: when my laptop died and `pip install -e .` hadn't been verified, I lost a full evening reconstructing the environment. The harness became load-bearing only after I stopped noticing it, which means any gap in recovery is catastrophic.

**7. Key-person dependency is the one risk that actually kept me awake.**
The Horizon C risk table calls this **"NEW HIGH RISK — if the operator stops working on it, there's no community to keep it alive."** The runbook's sustainability checklist warns: **"If you find yourself spending more time maintaining the harness than getting value from it, pause and re-evaluate."** I hit that wall around month eight. The only thing that brought me back was `harness review` saving me more time than maintenance cost me.

---

### 2. Recommended SHIP list (your top 3-5 rows to do FIRST)

| Rank | Row / Shift | Why |
|---|---|---|
| 1 | **Tier 1 Shift A** (auto-pick `lens-set` from file extension) | I genuinely don't remember whether `.py` needs `--lens-set code-review`. The harness should just know. This removes the **"did I remember the right flag?"** burden cited in the bloat audit. |
| 2 | **Tier 1 Shift F** (auto-pick `max_tokens` from prompt length) | Prevents another DeepSeek budget burn. For subscription engines the cost is zero anyway; for paid engines the explicit override still works. |
| 3 | **W13-INSTALL-VERIFY** | Closes **"the single hardest unknown: whether `pip install -e .` actually works"** (master audit). When my laptop dies, this is the difference between resurrection and project abandonment. |
| 4 | **W13-AUDIT-JSONL** | I have needed to answer **"what did I dispatch last Tuesday?"** three times this year. The Horizon C plan notes this was **"DeepSeek panel flagged"** and it's the foundation of every other ops row. |
| 5 | **Tier 1 Shift G** (unify `harness.review()` as SDK function) | I script client workflows in Python now; the CLI is too slow. This resolves the **"do I use dispatch or review?"** confusion the bloat audit identifies. |

---

### 3. Recommended DROP list (your top 2-4 rows to NOT do)

| Row | Why |
|---|---|
| **W13-BACKUP-ENCRYPTION** | The bloat audit asks honestly: **"genuine security need or paranoia for an internal tool where .env is already on disk in cleartext?"** A year later, my answer is paranoia. If someone has my laptop, they have my API keys. Encryption adds a recovery password I will forget. |
| **W13-PLUGIN-SANDBOX-PLAN** | The bloat audit lists option **"(d) accept the risk and document it (since internal-tool = trusted authors)."** I am the only author; a collaborator is a student I trust. Sandbox engineering is time I could spend on billable work. |
| **W14-BEST-OF-N** | DeepSeek flagged: **"could multiply costs by N per query, with no mention of cost caps."** As a solo operator, I never need engine consensus; I need speed. This is a conference-demo feature, not a Tuesday-afternoon feature. |
| **W13-VPS-OBSERVER-NAT-PLAN** (and all of Wave 17) | The Horizon C plan wisely says **"only if operator actually uses the VPS path."** A year later, I don't. I run the harness on my laptop. Kill the entire VPS track until there is a real deployment need. |

---

### 4. Recommended ADD list (your top 1-3 NEW rows worth adding)

| Row | Pitch | Effort |
|---|---|---|
| **`harness whoami`** |