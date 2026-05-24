<!-- persona=R3-architect status=OK (18525ms) -->

# R3-architect

**Headline verdict**  
YES‑IF the operator commits to a desktop chat app rather than bolting chat onto the CLI.

**Wave-count estimate**  
6 waves p50 (W11‑W16), confidence range 4‑10 waves (p90). First 3 waves are foundation (IPC, chat scaffold, first‑run wizard); next 3 polish and hide advanced verbs.

**The 3 most load‑bearing decisions in W11**

1. **Pick IPC mechanism** – REST over localhost (FastAPI auto‑started by Electron) is the only practical choice. Avoid stdin/stdout because the operator expects the Python backend to keep state across conversations. Commit to a single JSON‑based API contract for all verbs (`POST /chat {text}`, `GET /status`, etc.).

2. **Convert the 30+ verb CLI into a chat‑first command set** – Not all verbs become GUI buttons. Use a `*` precedence: the 5‑6 daily‑use verbs (today, morning‑brief, status list, preflight --fix, engines‑heal, harness daily) become one‑click buttons in the chat UI. The remaining 25+ verbs (coord subcommands, mutation, audit flags) are only accessible via typed chat commands, hidden behind a “/” prefix or a separate “advanced commands” panel.

3. **Build a first‑run wizard that replaces the broken preflight** – The `harness env-wizard` exists but is buried. In W11, create a single “Welcome” screen that checks git_clean, DPAPI, and Python venv, then walks the operator through fixing each issue with a one‑click action (e.g., “Commit your changes? [Yes] [Stash] [Show diff]”). The wizard must *succeed* every time, even if it means auto‑stashing or auto‑committing.

**The one thing to cut or hide**  
The entire `coord` pipeline (13 subcommands). A chat‑tier user never needs to see planner/worker/integrate. Hide behind a “/coord” chat command or a developer toggle. It adds visual noise and cognitive load.

**The one risk most likely to derail the trajectory**  
**Desktop app scope creep** – The operator may get tempted to add a dashboard, cost widget, email brief, etc. before the core chat loop works. Ship a minimal Electron shell with a single chat input box, a status bar (last preflight verdict), and the 5‑6 quick‑action buttons. Nothing else. Every new feature must be a chat‑driven command first, GUI second.

**Single‑sentence recommendation**  
Go – but force‑cut the coord subcommands and ship a bare‑bones Electron chat window in W11, then let the operator’s usage shape W12‑W16 buttons.
