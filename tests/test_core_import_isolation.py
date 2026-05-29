"""W14-RELIABILITY 2026-05-29: the core CLI import must NOT pull in heavy
machinery.

External reliability panels (DeepSeek + MiMo + Kimi) ranked this their #1
gap: `import harness.cli` was eager-loading ~7k LOC of `coord`/`observer`/
`loops`/`orchestrator`/`dashboard` machinery.  A bug *anywhere* in that code
would then break `harness ask` (the core verb) at startup, even for users who
never touch the machinery.

This test is Kimi's falsifiable YES-gate, codified: it imports `harness.cli`
in a FRESH subprocess (so it also dodges any in-session module contamination)
and asserts none of the machinery packages landed in ``sys.modules``.  If a
future change re-adds an eager import of the machinery, this test fails.
"""
import subprocess
import sys

# Heavy / agentic machinery that must stay OFF the core import path.  These are
# reachable via their (hidden) verbs, which lazy-import them on invocation.
_FORBIDDEN_PREFIXES = (
    "harness.coord",
    "harness.observer",
    "harness.loops",
    "harness.orchestrator",
    "harness.dashboard",
)


def test_core_cli_import_loads_no_machinery():
    code = (
        "import sys, harness.cli\n"
        "pref = " + repr(_FORBIDDEN_PREFIXES) + "\n"
        "leaked = sorted(m for m in sys.modules "
        "if any(m == p or m.startswith(p + '.') for p in pref))\n"
        "print('LEAKED=' + ','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        "Core `import harness.cli` eager-loaded machinery that must be lazy "
        f"(reliability regression). {proc.stdout.strip()} {proc.stderr.strip()}"
    )
