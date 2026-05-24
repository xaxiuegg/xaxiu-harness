### Verdict
BLOCKED

### Confidence
0.45

### Top-3 concrete recommendations

1. **Replace Unicode glyphs in CLI output with ASCII-safe equivalents and validate under a real Windows cp1252 console, because pytest/CliRunner masks the encoding crashes seen in live use.**  
   *Grounded in:* evidence 04 (preflight `→` crash), evidence 06 (help `α` crash), evidence 15 (agent init `✓` crash).  
   *Effort:* S

2. **Register the missing dashboard API routers for `/cost`, `/preflight_latency`, and `/l5_events`, then add a live-dashboard smoke test that polls each endpoint and asserts the widgets render real data rather than 404.**  
   *Grounded in:* evidence 09–14 (all return `{"detail":"Not Found"}`).  
   *Effort:* M

3. **Run a "fresh clone on bare OS" integration drill—without developer dotfiles or pre-existing state—to force real bootstrap paths like agent init, default adapter creation, and observer scheduler registration, because the E2E proof caught `adapter_load_failed` only after 2141 mocked tests passed.**  
   *Grounded in:* evidence 18 (first real call crashed) and evidence 15 (agent init dry run).  
   *Effort:* M

### Operator vote
WAIT-FOR-WAVE-12

### Single quote from evidence
"Previously the SDK had only unit-test coverage (monkeypatched dispatch_packet); this is the first real-engine validation."