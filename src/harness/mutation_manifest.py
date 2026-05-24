"""W9-MUTATION-MANIFEST: read + validate coord/mutation_targets.yaml.

Single source of truth for which modules have mutation coverage,
when they were last swept, and what kill-rate they cleared.  Drives:

  - scripts/run_mutation_canary.py default rotation
  - scripts/run_mutation_sweep.py module list
  - tests/test_mutation_manifest.py CI gate (schema + staleness)
  - harness mutation status (operator-facing report)

Module tiers:
    hot   — load-bearing dispatch path; full 5-mutant sweep, ≥3 kills
    warm  — canary-rotated; 3-mutant spot-check, ≥1 kill = success
    cold  — best-effort; no sweep required, but flagged when source
            changes substantially after the last sweep SHA
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "coord" / "mutation_targets.yaml"

# Staleness thresholds: number of days since last_sweep_date a module
# can go without re-sweep before being flagged.  Per tier.
STALENESS_DAYS: dict[str, int] = {
    "hot": 30,
    "warm": 60,
    "cold": 120,
}


Tier = Literal["hot", "warm", "cold"]


@dataclass
class MutationTemplate:
    label: str
    search: str
    replace: str


@dataclass
class ModuleTarget:
    path: str
    tier: Tier
    last_sweep_sha: str | None
    last_sweep_date: str | None
    expected_kill_rate: float | None = None
    notes: str = ""

    @property
    def has_sweep(self) -> bool:
        return self.last_sweep_sha is not None

    def days_since_sweep(self, now: datetime | None = None) -> int | None:
        if self.last_sweep_date is None:
            return None
        try:
            d = datetime.fromisoformat(self.last_sweep_date)
        except ValueError:
            return None
        # Treat as midnight UTC if no tz
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        return (now - d).days

    def is_stale(self, now: datetime | None = None) -> bool:
        """Cold tier is never stale (no required cadence)."""
        if self.tier == "cold":
            return False
        days = self.days_since_sweep(now)
        if days is None:
            return True  # never swept = stale
        return days > STALENESS_DAYS.get(self.tier, 30)


@dataclass
class Manifest:
    schema_version: int
    sweep_template: list[MutationTemplate]
    modules: list[ModuleTarget]

    def by_tier(self, tier: Tier) -> list[ModuleTarget]:
        return [m for m in self.modules if m.tier == tier]

    def stale_modules(self, now: datetime | None = None) -> list[ModuleTarget]:
        return [m for m in self.modules if m.is_stale(now)]

    def find(self, path: str) -> ModuleTarget | None:
        for m in self.modules:
            if m.path == path:
                return m
        return None


def load(path: Path | None = None) -> Manifest:
    """Read + validate the mutation manifest.  Raises ValueError on
    schema violation."""
    p = path or MANIFEST_PATH
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"mutation manifest not found: {p}")
    except yaml.YAMLError as exc:
        raise ValueError(f"mutation manifest parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("mutation manifest must be a YAML mapping")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError(
            f"unsupported schema_version: {schema_version} "
            f"(expected 1)"
        )

    templates_raw = raw.get("sweep_template") or []
    templates = [
        MutationTemplate(
            label=t["label"], search=t["search"], replace=t["replace"],
        )
        for t in templates_raw
    ]

    modules_raw = raw.get("modules") or []
    modules: list[ModuleTarget] = []
    for m in modules_raw:
        tier = m.get("tier", "cold")
        if tier not in ("hot", "warm", "cold"):
            raise ValueError(
                f"module {m.get('path')!r}: unknown tier {tier!r}"
            )
        modules.append(ModuleTarget(
            path=m["path"],
            tier=tier,
            last_sweep_sha=m.get("last_sweep_sha"),
            last_sweep_date=m.get("last_sweep_date"),
            expected_kill_rate=m.get("expected_kill_rate"),
            notes=m.get("notes", ""),
        ))
    return Manifest(
        schema_version=schema_version,
        sweep_template=templates,
        modules=modules,
    )


def render_status_report(manifest: Manifest,
                         now: datetime | None = None) -> str:
    """Plain-text status report for the operator.

    Lists each tier and flags stale modules.  Designed to be read by
    a non-technical operator (no Python jargon).
    """
    now = now or datetime.now(timezone.utc)
    lines = [
        "Mutation coverage status",
        "=" * 40,
    ]
    for tier in ("hot", "warm", "cold"):
        modules = manifest.by_tier(tier)
        if not modules:
            continue
        lines.append(f"\n## {tier.upper()} ({len(modules)} modules)")
        for m in modules:
            days = m.days_since_sweep(now)
            if days is None:
                age = "never swept"
            else:
                age = f"{days}d ago"
            stale = " STALE" if m.is_stale(now) else ""
            kr = (f" kill_rate={m.expected_kill_rate}"
                  if m.expected_kill_rate is not None else "")
            lines.append(f"  - {m.path}  [{age}]{stale}{kr}")
    stale = manifest.stale_modules(now)
    if stale:
        lines.append(f"\nStale modules ({len(stale)}) — schedule a sweep:")
        for m in stale:
            lines.append(f"  - {m.path}")
    else:
        lines.append("\nAll hot+warm modules are within their sweep cadence.")
    return "\n".join(lines)
