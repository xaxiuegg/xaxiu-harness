"""Independent harness observer (the check on dev-manager authority).

Roster #20. Runs outside dev-manager authority via separate Task Scheduler
tasks; audits via cross-engine dispatch.
"""

from __future__ import annotations

from harness.observer.flags import Flag, FlagSeverity

# W14-TRIM 2026-05-29: run_cycle / CycleReport are intentionally NOT re-exported
# at package level.  Re-exporting them here made `import harness.observer.<x>`
# (or any submodule import) pull in observer.cycle, which transitively imports
# ALL of coord.* (~3.2k LOC) — putting the heavy machinery on the core
# `import harness.cli` path (reliability risk: a bug there breaks `ask` at
# startup).  Import them directly from harness.observer.cycle where needed.
__all__ = ["Flag", "FlagSeverity"]
