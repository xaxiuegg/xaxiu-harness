"""Entry point for ``python -m harness ...``.

Without this file, ``python -m harness.cli <verb>`` silently exits 0
because Python loads the module but never invokes the click group.
The coordinator's worker-spawn ``Popen([sys.executable, '-m',
'harness.cli', 'coord', 'work', ...])`` relied on that broken path
and produced zero progress in real coord runs — battle-test smoke
2026-05-22 surfaced it.

Use ``python -m harness coord work ...`` going forward.  The legacy
``harness`` console-script entry (``[project.scripts]`` in
pyproject.toml) still works for pip-installed users.
"""

from __future__ import annotations

from harness.cli import main


if __name__ == "__main__":
    main()
