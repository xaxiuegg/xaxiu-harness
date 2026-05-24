### Verdict
`NEEDS-WORK`

### Confidence
0.82

### Top-3 concrete recommendations

1. **Mount the existing cost, latency, and L5 Python modules to the dashboard FastAPI router** so `/api/cost`, `/api/preflight-latency`, and `/api/l5-events` return live JSON instead of 404; the backend modules already work in CLI.  
   *Grounded in:* evidence 12, 13, 14 return `{"detail":"Not Found"}` while 02, 05, and 07 prove the data exists.  
   *Effort:* S

2. **Add a red stale-data banner to the dashboard header** when the loop tick is >1 hour old; the current view silently displays a "THREE DAYS STALE" loop as if the system is healthy.  
   *Grounded in:* evidence 00 line "Last tick 2026-05-21T00:02:35Z — THREE DAYS STALE".  
   *Effort:* S

3. **Render L5 escalations as a persistent, top-of-viewport banner in the dashboard HTML** (not just a CLI endpoint), because the L5 contract spec requires the banner to "ALWAYS surface to dashboard" for operator incident response.  
   *Grounded in:* evidence 00 "NO L5 banner" and 16 W11-L5-OUTPUT-CONTRACT notes.  
   *Effort:* M

### Operator vote
`WAIT-FOR-WAVE-12`

### Single quote from evidence
> "NOTABLE GAPS: NO cost widget, NO L5 banner, NO preflight latency, NO recent commit list — none of the Wave 11 work is surfaced."