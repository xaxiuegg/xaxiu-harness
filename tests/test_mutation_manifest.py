"""W9-MUTATION-MANIFEST: schema + staleness gate for coord/mutation_targets.yaml.

The manifest is the single source of truth for mutation coverage
across src/harness/ modules.  These tests:

  1. Verify the on-disk manifest parses + validates.
  2. Verify the staleness rules per tier.
  3. Verify the operator-facing status report renders without crash.
  4. Lock in the hot-tier modules so the dispatch path can't lose
     coverage silently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness import mutation_manifest as mm


def test_canonical_manifest_loads_and_validates():
    """The on-disk manifest must parse + validate at every commit."""
    manifest = mm.load()
    assert manifest.schema_version == 1
    assert manifest.modules, "Manifest has no modules — won't gate anything"
    assert manifest.sweep_template, "Sweep template missing"


def test_canonical_manifest_includes_all_hot_modules():
    """Hot tier is load-bearing dispatch path.  Removing one is a
    regression that must trip the test."""
    manifest = mm.load()
    hot_paths = {m.path for m in manifest.by_tier("hot")}
    required = {
        "src/harness/engines/dispatcher.py",
        "src/harness/engines/concrete.py",
        "src/harness/coord/worker.py",
        "src/harness/coord/integrator.py",
        "src/harness/orchestrator.py",
    }
    missing = required - hot_paths
    assert not missing, f"Hot tier missing required modules: {missing}"


def test_canonical_manifest_warm_includes_canary_rotation():
    """The W9-MUTATION-CANARY rotation modules must be in warm tier."""
    manifest = mm.load()
    warm_paths = {m.path for m in manifest.by_tier("warm")}
    # Canary rotation per scripts/run_mutation_canary.py
    canary_rotation = {
        "src/harness/proxy/circuit.py",
        "src/harness/observer/cycle.py",
        "src/harness/loops/runner.py",
        "src/harness/dashboard/app.py",
    }
    missing = canary_rotation - warm_paths
    assert not missing, f"Warm tier missing canary rotation modules: {missing}"


def test_load_rejects_unknown_schema_version(tmp_path):
    bad = tmp_path / "manifest.yaml"
    bad.write_text("schema_version: 99\nmodules: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        mm.load(bad)


def test_load_rejects_unknown_tier(tmp_path):
    bad = tmp_path / "manifest.yaml"
    bad.write_text(
        "schema_version: 1\n"
        "sweep_template: []\n"
        "modules:\n"
        "  - path: src/harness/foo.py\n"
        "    tier: unknown-tier\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown tier"):
        mm.load(bad)


def test_load_handles_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        mm.load(tmp_path / "nonexistent.yaml")


def test_load_handles_invalid_yaml(tmp_path):
    bad = tmp_path / "manifest.yaml"
    bad.write_text("not valid: yaml: : : :", encoding="utf-8")
    with pytest.raises(ValueError, match="parse error"):
        mm.load(bad)


# -- ModuleTarget staleness ------------------------------------------------


def _mk_target(*, tier: str, days_old: int | None) -> mm.ModuleTarget:
    if days_old is None:
        date_str = None
    else:
        d = datetime.now(timezone.utc) - timedelta(days=days_old)
        date_str = d.strftime("%Y-%m-%d")
    return mm.ModuleTarget(
        path="src/harness/test.py",
        tier=tier,
        last_sweep_sha="abc" if date_str else None,
        last_sweep_date=date_str,
    )


def test_hot_module_stale_after_30_days():
    t = _mk_target(tier="hot", days_old=31)
    assert t.is_stale()


def test_hot_module_fresh_within_30_days():
    t = _mk_target(tier="hot", days_old=15)
    assert not t.is_stale()


def test_warm_module_stale_after_60_days():
    assert _mk_target(tier="warm", days_old=61).is_stale()
    assert not _mk_target(tier="warm", days_old=59).is_stale()


def test_cold_module_never_stale():
    """Cold modules have no required cadence."""
    assert not _mk_target(tier="cold", days_old=None).is_stale()
    assert not _mk_target(tier="cold", days_old=365).is_stale()


def test_never_swept_module_is_stale_unless_cold():
    assert _mk_target(tier="hot", days_old=None).is_stale()
    assert _mk_target(tier="warm", days_old=None).is_stale()
    assert not _mk_target(tier="cold", days_old=None).is_stale()


def test_invalid_date_treated_as_never_swept():
    t = mm.ModuleTarget(
        path="src/foo.py", tier="hot",
        last_sweep_sha="abc", last_sweep_date="not-a-date",
    )
    assert t.days_since_sweep() is None
    assert t.is_stale()


# -- Manifest helpers -----------------------------------------------------


def test_manifest_find_returns_module_or_none():
    manifest = mm.load()
    found = manifest.find("src/harness/engines/dispatcher.py")
    assert found is not None
    assert found.tier == "hot"
    assert manifest.find("src/harness/does-not-exist.py") is None


def test_manifest_stale_modules_returns_subset():
    manifest = mm.load()
    # Force a future "now" so all dated modules look ancient
    future = datetime.now(timezone.utc) + timedelta(days=400)
    stale = manifest.stale_modules(now=future)
    # All hot + warm modules with a date should be stale at that point
    hot_warm = [m for m in manifest.modules if m.tier in ("hot", "warm")]
    assert len(stale) >= 1
    # Cold modules without dates aren't in the stale list
    cold_undated = [m for m in manifest.modules
                    if m.tier == "cold" and m.last_sweep_date is None]
    for cm in cold_undated:
        assert cm not in stale


# -- Status report --------------------------------------------------------


def test_render_status_report_includes_each_tier():
    manifest = mm.load()
    body = mm.render_status_report(manifest)
    assert "HOT" in body
    assert "WARM" in body
    # First hot module should appear
    assert "dispatcher.py" in body


def test_render_status_report_flags_never_swept():
    manifest = mm.load()
    body = mm.render_status_report(manifest)
    # Some warm modules have last_sweep_sha=null in the canonical manifest
    assert "never swept" in body.lower() or "STALE" in body
