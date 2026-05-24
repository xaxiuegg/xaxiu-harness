"""W9-SILENT-EXCEPTION-AUDIT: lint gate.

Locks in the W9 baseline of ZERO broad-undocumented silent excepts
in the production hot-path (engines/, coord/, state/, proxy/,
observer/, dispatch/).

A failing test means someone added a new ``except Exception: pass``
or ``except Exception: continue`` in the hot-path without either:

  - converting to a typed exception (the typical resolution), or
  - using the dispatcher's ``_swallow_telemetry`` helper, or
  - adding a 1-line comment above OR after the except describing
    why silence is intentional (cleanup, best-effort telemetry, etc.)

To fix: pick the resolution that matches the site's intent; do NOT
turn the lint off without operator sign-off.  Suppressing the lint
itself was the failure mode that hid the W8 schema bug.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_silent_excepts.py"
_spec = importlib.util.spec_from_file_location("audit_silent_excepts", _SCRIPT)
audit = importlib.util.module_from_spec(_spec)
sys.modules["audit_silent_excepts"] = audit
_spec.loader.exec_module(audit)


def test_no_broad_undocumented_silent_excepts_in_hotpath():
    """Regression gate — the count must stay at zero or the operator
    accepts a new broad swallow and updates this test's baseline."""
    findings = audit.scan_repo()
    broad_undoc = [
        f for f in findings
        if f.classification == "broad" and f.is_hotpath and not f.documented
    ]
    if broad_undoc:
        lines = [
            f"NEW broad-undocumented silent excepts found in hot-path. "
            f"Add a comment, convert to typed exception, or use a "
            f"swallow-helper.  Sites:",
        ]
        for f in broad_undoc:
            lines.append(
                f"  - {f.path}:{f.lineno} `except "
                f"{' / '.join(f.handler_types)}: {f.body_op}`"
            )
        raise AssertionError("\n".join(lines))


def test_audit_inventory_doc_can_be_rebuilt():
    """The audit doc must be reproducible from the script — no manual
    fixups creep in."""
    findings = audit.scan_repo()
    body = audit.format_report(findings)
    # Sanity checks on report shape
    assert "# Silent-except inventory" in body
    assert "## BROAD in hot-path WITHOUT" in body
    assert "## BROAD in hot-path WITH justification" in body
    assert "## TIGHT in hot-path" in body
    # The trailing-comment-recognition matters: count of broad in hot
    # path stays nonzero (those are valid documented sites)
    broad_hot = [f for f in findings
                 if f.classification == "broad" and f.is_hotpath]
    assert len(broad_hot) > 0  # we don't expect to ever hit zero broad


def test_find_silent_excepts_detects_inline_pass(tmp_path):
    """Self-check the detector: simple ``except: pass`` should be found."""
    src = (
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception:\n"
        "        pass\n"
    )
    fixture = tmp_path / "victim.py"
    fixture.write_text(src, encoding="utf-8")
    findings = audit.find_silent_excepts(fixture, src)
    assert len(findings) == 1
    assert findings[0].classification == "broad"
    assert findings[0].body_op == "pass"
    assert findings[0].documented is False


def test_find_silent_excepts_recognizes_inline_trailing_comment(tmp_path):
    """``pass  # best-effort`` should count as documented."""
    src = (
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except Exception:\n"
        "        pass  # best-effort cleanup\n"
    )
    fixture = tmp_path / "victim.py"
    fixture.write_text(src, encoding="utf-8")
    findings = audit.find_silent_excepts(fixture, src)
    assert len(findings) == 1
    assert findings[0].documented is True


def test_find_silent_excepts_recognizes_comment_above(tmp_path):
    src = (
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    # best-effort\n"
        "    except Exception:\n"
        "        pass\n"
    )
    fixture = tmp_path / "victim.py"
    fixture.write_text(src, encoding="utf-8")
    findings = audit.find_silent_excepts(fixture, src)
    assert len(findings) == 1
    assert findings[0].documented is True


def test_find_silent_excepts_classifies_tight_as_non_broad(tmp_path):
    src = (
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except OSError:\n"
        "        pass\n"
    )
    fixture = tmp_path / "victim.py"
    fixture.write_text(src, encoding="utf-8")
    findings = audit.find_silent_excepts(fixture, src)
    assert len(findings) == 1
    assert findings[0].classification == "tight"


def test_find_silent_excepts_handles_continue_body(tmp_path):
    src = (
        "def f():\n"
        "    for i in range(3):\n"
        "        try:\n"
        "            x = i\n"
        "        except Exception:\n"
        "            continue\n"
    )
    fixture = tmp_path / "victim.py"
    fixture.write_text(src, encoding="utf-8")
    findings = audit.find_silent_excepts(fixture, src)
    assert len(findings) == 1
    assert findings[0].body_op == "continue"
    assert findings[0].classification == "broad"
